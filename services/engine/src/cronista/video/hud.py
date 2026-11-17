"""Detecção universal de HUD oculto (Fase 3B).

Sem conhecer o jogo: o HUD é o que fica **no mesmo lugar** enquanto o mundo muda. A sessão inteira define uma
máscara de pixels estáveis e com borda (o gabarito do HUD); depois cada segundo mede o quanto o quadro
ainda bate com ele. Trecho longo sem o gabarito, em cena de jogo (nem tela preta nem menu), é HUD oculto.
Confiança baixa de propósito: é pista para B-roll limpo, não verdade.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from cronista.audio.events import EVENTS_KEY, events_from_result, write_events_file
from cronista.audio.signals import SIGNALS_KEY, load_signal, signal_metas, write_signal
from cronista.config import Settings
from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource, params_hash
from cronista.domain.frames import FPS
from cronista.domain.models import StageResult
from cronista.pipeline.stage import StageContext, StageError
from cronista.video import frames as vframes

Gray = npt.NDArray[np.uint8]
FloatArray = npt.NDArray[np.float32]
BoolArray = npt.NDArray[np.bool_]
BLOCKED = frozenset({"menu", "loading", "pausa", "idle"})


@dataclass(frozen=True)
class HudParams:
    tol: int = 14
    """Diferença de brilho (0 a 255) abaixo da qual um pixel "bate" com o gabarito."""
    stable_frac: float = 0.7
    """Fração das amostras em que o pixel precisa bater com a mediana para entrar na máscara."""
    min_grad: float = 25.0
    """Borda mínima do gabarito (diferença para o vizinho): descarta fundo liso e escuro."""
    min_mask_frac: float = 0.01
    """Máscara com menos que isso da tela: a sessão não tem HUD estável (nada a detectar)."""
    hidden_match: float = 0.15
    """Abaixo disso quase nada do HUD bate: HUD oculto. Painel aberto sobre o jogo deixa 0,2 a 0,45."""
    min_seconds: float = 6.0
    max_blocked: float = 0.3
    """Fração do trecho em menu/loading/pausa/idle acima da qual não é HUD oculto, é outra tela."""
    max_edge: float = 0.12
    """Bordas por segundo acima das quais a tela é de interface (texto, caixas)."""
    template_stride: int = 8
    """Uma amostra a cada tantas (a 1 fps) forma o gabarito: memória constante em sessão de 10 h."""


@dataclass(frozen=True)
class HudTemplate:
    mask: BoolArray
    median: Gray

    @property
    def usable(self) -> bool:
        return bool(self.mask.any())


def build_template(sample: Gray, params: HudParams) -> HudTemplate:
    """Máscara e mediana a partir de amostras `(n, h, w)` espalhadas pela sessão."""
    if len(sample) < 10:
        return HudTemplate(np.zeros(sample.shape[1:], bool), np.zeros(sample.shape[1:], np.uint8))
    med = np.median(sample, axis=0).astype(np.uint8)
    stable = (np.abs(sample.astype(np.int16) - med.astype(np.int16)) <= params.tol).mean(axis=0)
    m = med.astype(np.int16)
    grad = np.zeros(m.shape, np.int16)
    grad[:, 1:] = np.maximum(grad[:, 1:], np.abs(np.diff(m, axis=1)))
    grad[1:, :] = np.maximum(grad[1:, :], np.abs(np.diff(m, axis=0)))
    edges = grad >= params.min_grad
    near = edges.copy()  # o miolo de uma barra ou caixa também é HUD: dilata a borda em 3 pixels
    for _ in range(3):
        grown = near.copy()
        grown[:, 1:] |= near[:, :-1]
        grown[:, :-1] |= near[:, 1:]
        grown[1:, :] |= near[:-1, :]
        grown[:-1, :] |= near[1:, :]
        near = grown
    mask = (stable >= params.stable_frac) & near
    if mask.mean() < params.min_mask_frac:
        return HudTemplate(np.zeros_like(mask), med)
    return HudTemplate(mask, med)


def match(frames: Gray, template: HudTemplate, params: HudParams) -> FloatArray:
    """Fração (0 a 1) dos pixels do HUD que ainda bate com o gabarito, por quadro."""
    if not template.usable:
        return np.ones(len(frames), np.float32)
    px = frames[:, template.mask].astype(np.int16)
    ref = template.median[template.mask].astype(np.int16)
    return (np.abs(px - ref) <= params.tol).mean(axis=1).astype(np.float32)


def hidden_spans(
    score: FloatArray, blocked: BoolArray, params: HudParams, per_second: int = 1
) -> list[tuple[int, int, float]]:
    """Trechos `(inicio, fim, confiança)` em amostras com o gabarito ausente por tempo suficiente."""
    low = (score < params.hidden_match) & ~blocked
    out: list[tuple[int, int, float]] = []
    i, n = 0, len(low)
    while i < n:
        if not low[i]:
            i += 1
            continue
        j = i
        while j < n and low[j]:
            j += 1
        if (j - i) >= params.min_seconds * per_second:
            conf = float(np.clip(0.5 * (1.0 - score[i:j].mean() / params.hidden_match), 0.05, 0.5))
            out.append((i, j, conf))
        i = j
    return out


class HudStage:
    """Eventos `hud_oculto`: trechos de cena de jogo sem o HUD que a sessão mostra no resto do tempo."""

    name = "video_hud"
    version = "3"
    needs: tuple[str, ...] = ("proxy", "video_scenes", "video_signals")
    uses_gpu = False

    def __init__(self, params: HudParams | None = None) -> None:
        self.hud = params or HudParams()

    def params(self, settings: Settings) -> dict[str, Any]:
        return dict(self.hud.__dict__)

    def run(self, ctx: StageContext) -> StageResult:
        proxy = Path(str(ctx.inputs["proxy"].data.get("proxy", "")))
        if not proxy.is_file():
            raise StageError(f"proxy não encontrado: {proxy} (rode a ingestão de novo)")
        sample: list[Gray] = []
        seen = 0
        for block in vframes.iter_gray_blocks(ctx.settings, proxy, sample_fps=1):
            for k in range(len(block)):
                if (seen + k) % self.hud.template_stride == 0:
                    sample.append(block[k].copy())
            seen += len(block)
        if not sample:
            raise StageError("nenhum quadro lido do proxy")
        template = build_template(np.stack(sample), self.hud)
        warnings: list[str] = []
        scores: list[FloatArray] = []
        if not template.usable:
            warnings.append("sem HUD estável nesta sessão: nenhum trecho de HUD oculto é detectável")
        else:
            blocks = vframes.iter_gray_blocks(
                ctx.settings, proxy, sample_fps=1, between_blocks=ctx.wait_for_gpu
            )
            for block in blocks:
                scores.append(match(block, template, self.hud))
        score = np.concatenate(scores) if scores else np.ones(seen, np.float32)
        blocked = np.zeros(len(score), bool)
        for e in events_from_result(ctx.inputs["video_scenes"]) or []:
            if e.kind in BLOCKED:
                blocked[e.evidence.start_frame // FPS : -(-e.evidence.end_frame // FPS)] = True
        edge = np.asarray(
            load_signal(signal_metas(ctx.inputs["video_signals"])["video.edge_density"]).values, np.float32
        )
        per_s = vframes.SAMPLE_FPS
        usable = len(edge) // per_s * per_s
        by_second = edge[:usable].reshape(-1, per_s).mean(axis=1)
        n = min(len(by_second), len(blocked))
        blocked[:n] |= by_second[:n] > self.hud.max_edge
        digest = params_hash(self.params(ctx.settings))
        events = [
            AnalysisEvent(
                kind="hud_oculto",
                evidence=Evidence(
                    source=EvidenceSource.CENA,
                    start_frame=a * FPS,
                    end_frame=b * FPS,
                    confidence=conf,
                    model="video-heuristica",
                    model_version=self.version,
                    params_hash=digest,
                ),
                payload={"match_medio": float(score[a:b].mean()), "pixels_hud": int(template.mask.sum())},
            )
            for a, b, conf in hidden_spans(score, blocked, self.hud)
        ]
        path = write_events_file(ctx.out_dir, events)
        meta = write_signal(
            ctx.out_dir,
            "video.hud_match",
            score,
            unit="0-1",
            source_track="video",
            version=self.version,
            params=self.params(ctx.settings),
            hop_frames=FPS,
            model="video-heuristica",
        )
        return StageResult(
            files=[path, meta.path],
            data={
                EVENTS_KEY: path,
                "count": len(events),
                SIGNALS_KEY: {"video.hud_match": meta.model_dump()},
            },
            warnings=warnings,
        )


@dataclass(frozen=True)
class IdleParams:
    still_min: float = 0.90
    """Fração de pixels parados (sinal `still` da 3A) para a cena contar como parada."""
    hud_full: float = 0.9
    """HUD inteiro à vista: painel, chat ou boas-vindas cobrem parte dele (0,2 a 0,85)."""
    dark_luma: float = 0.03
    min_seconds: float = 10.0


def idle_spans(
    still: FloatArray, luma: FloatArray, hud_match: FloatArray, params: IdleParams
) -> list[tuple[int, int, float]]:
    """Trechos `(inicio, fim, confiança)` em segundos: cena de jogo parada, com o HUD inteiro à vista."""
    n = min(len(still), len(luma), len(hud_match))
    ok = (still[:n] >= params.still_min) & (hud_match[:n] >= params.hud_full) & (luma[:n] >= params.dark_luma)
    out: list[tuple[int, int, float]] = []
    i = 0
    while i < n:
        if not ok[i]:
            i += 1
            continue
        j = i
        while j < n and ok[j]:
            j += 1
        if j - i >= params.min_seconds:
            conf = float(
                np.clip(
                    0.3 + 0.4 * (hud_match[i:j].mean() - params.hud_full) / (1 - params.hud_full), 0.3, 0.7
                )
            )
            out.append((i, j, conf))
        i = j
    return out


class IdleStage:
    """Eventos `idle`: personagem parado com o jogo rodando (cena parada e HUD inteiro, nunca menu)."""

    name = "video_idle"
    version = "1"
    needs: tuple[str, ...] = ("video_signals", "video_hud")
    uses_gpu = False

    def __init__(self, params: IdleParams | None = None) -> None:
        self.idle = params or IdleParams()

    def params(self, settings: Settings) -> dict[str, Any]:
        return dict(self.idle.__dict__)

    def run(self, ctx: StageContext) -> StageResult:
        if ctx.inputs["video_hud"].warnings:  # sem HUD estável não há como separar jogo de tela de interface
            path = write_events_file(ctx.out_dir, [])
            return StageResult(
                files=[path],
                data={EVENTS_KEY: path, "count": 0},
                warnings=["sem HUD estável nesta sessão: idle não detectável"],
            )
        sig = signal_metas(ctx.inputs["video_signals"])
        per_s = vframes.SAMPLE_FPS

        def by_second(name: str) -> FloatArray:
            v = np.asarray(load_signal(sig[f"video.{name}"]).values, np.float32)
            return v[: len(v) // per_s * per_s].reshape(-1, per_s).mean(axis=1)

        match_s = np.asarray(
            load_signal(signal_metas(ctx.inputs["video_hud"])["video.hud_match"]).values, np.float32
        )
        digest = params_hash(self.params(ctx.settings))
        events = [
            AnalysisEvent(
                kind="idle",
                evidence=Evidence(
                    source=EvidenceSource.CENA,
                    start_frame=a * FPS,
                    end_frame=b * FPS,
                    confidence=conf,
                    model="video-heuristica",
                    model_version=self.version,
                    params_hash=digest,
                ),
                payload={"motivo": "cena parada com o HUD inteiro", "hud_match": float(match_s[a:b].mean())},
            )
            for a, b, conf in idle_spans(by_second("still"), by_second("luma_mean"), match_s, self.idle)
        ]
        path = write_events_file(ctx.out_dir, events)
        return StageResult(files=[path], data={EVENTS_KEY: path, "count": len(events)})

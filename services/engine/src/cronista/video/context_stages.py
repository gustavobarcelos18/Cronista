"""Etapas da 3B: embeddings de quadro (GPU), contextos visuais e linha de base do áudio por contexto."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from cronista.audio import dsp
from cronista.audio.events import EVENTS_KEY, events_from_result, write_events_file
from cronista.audio.signals import (
    HOP_FRAMES as AUDIO_HOP,
)
from cronista.audio.signals import (
    SIGNALS_KEY,
    SignalMeta,
    load_signal,
    signal_metas,
    write_signal,
)
from cronista.config import Settings
from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource, params_hash
from cronista.domain.frames import FPS
from cronista.domain.models import StageResult
from cronista.pipeline.stage import StageContext, StageError
from cronista.video import frames as vframes
from cronista.video.broll import BrollParams, candidates, hud_state, score_candidate, text_bank, theme_tags
from cronista.video.contexts import NO_CONTEXT, ContextParams, cluster, runs
from cronista.video.hud import HAS_HUD_KEY
from cronista.video.ports import FrameEmbedder

EMBED_FPS = 1
EMBED_HOP = FPS // EMBED_FPS
"""Quadros a 60 fps entre dois embeddings (1 por segundo)."""
EMBEDDINGS_KEY = "embeddings"


class EmbeddingsStage:
    """Um embedding por segundo do proxy, em `float16` (N x D) no cache; só a referência vai no resultado."""

    name = "video_embeddings"
    version = "1"
    needs: tuple[str, ...] = ("proxy",)
    uses_gpu = True

    def __init__(self, embedder: FrameEmbedder) -> None:
        self.embedder = embedder

    def params(self, settings: Settings) -> dict[str, Any]:
        e = self.embedder
        return {"embedder": [e.name, e.version, e.options], "fps": EMBED_FPS, "size": e.input_size}

    def run(self, ctx: StageContext) -> StageResult:
        proxy = Path(str(ctx.inputs["proxy"].data.get("proxy", "")))
        if not proxy.is_file():
            raise StageError(f"proxy não encontrado: {proxy} (rode a ingestão de novo)")
        parts: list[Any] = []
        for block in vframes.iter_rgb_blocks(
            ctx.settings,
            proxy,
            sample_fps=EMBED_FPS,
            size=self.embedder.input_size,
            between_blocks=ctx.wait_for_gpu,
        ):
            emb = np.asarray(self.embedder.embed_images(block, pause=ctx.wait_for_gpu), dtype=np.float32)
            if emb.shape != (len(block), self.embedder.dim):
                raise StageError(
                    f"embedder devolveu {emb.shape}, esperado ({len(block)}, {self.embedder.dim})"
                )
            parts.append(emb.astype(np.float16))
        if not parts:
            raise StageError("nenhum quadro lido do proxy (vídeo vazio ou sem trilha de vídeo)")
        path = ctx.out_dir / "embeddings.npy"
        np.save(path, np.concatenate(parts))
        return StageResult(
            files=[str(path)],
            data={EMBEDDINGS_KEY: {"path": str(path), "fps": EMBED_FPS, "dim": self.embedder.dim}},
        )


def load_embeddings(result: StageResult) -> Any:
    info = result.data.get(EMBEDDINGS_KEY)
    if not info:
        raise StageError("resultado sem embeddings")
    return np.load(info["path"], mmap_mode="r")


class ContextsStage:
    """Agrupa os embeddings em contextos da sessão: eventos `contexto` e o sinal `video.context` (1 Hz)."""

    name = "video_contexts"
    version = "1"
    needs: tuple[str, ...] = ("video_embeddings",)
    uses_gpu = False

    def __init__(self, params: ContextParams | None = None) -> None:
        self.context = params or ContextParams()

    def params(self, settings: Settings) -> dict[str, Any]:
        return dict(self.context.__dict__)

    def run(self, ctx: StageContext) -> StageResult:
        emb = np.asarray(load_embeddings(ctx.inputs["video_embeddings"]), dtype=np.float32)
        result = cluster(emb, 1.0 / EMBED_FPS, self.context)
        digest = params_hash(self.params(ctx.settings))
        events: list[AnalysisEvent] = []
        for start, end, label in runs(result.labels):
            if label == NO_CONTEXT:
                continue
            members = result.labels[start:end]
            centroid = result.centroids[label]
            conf = float(np.clip(np.mean(emb[start:end] @ centroid), 0.0, 1.0)) if len(members) else 0.0
            events.append(
                AnalysisEvent(
                    kind="contexto",
                    evidence=Evidence(
                        source=EvidenceSource.CENA,
                        start_frame=start * EMBED_HOP,
                        end_frame=end * EMBED_HOP,
                        confidence=conf,
                        model="video-contextos",
                        model_version=self.version,
                        params_hash=digest,
                    ),
                    payload={
                        "context_id": label,
                        "representative_frame": result.contexts[label].representative * EMBED_HOP,
                    },
                )
            )
        path = write_events_file(ctx.out_dir, events)
        meta = write_signal(
            ctx.out_dir,
            "video.context",
            result.labels.astype(np.float32),
            unit="id",
            source_track="video",
            version=self.version,
            params=self.params(ctx.settings),
            hop_frames=EMBED_HOP,
            model="video-contextos",
        )
        warnings = []
        if not result.contexts:
            warnings.append(
                "nenhum contexto com tempo suficiente: o áudio fica só com a linha de base da sessão"
            )
        return StageResult(
            files=[str(path), meta.path],
            data={
                EVENTS_KEY: path,
                "count": len(events),
                SIGNALS_KEY: {"video.context": meta.model_dump()},
                "contexts": [
                    {"id": c.id, "seconds": c.seconds, "representative_frame": c.representative * EMBED_HOP}
                    for c in result.contexts
                ],
            },
            warnings=warnings,
        )


class ContextNoveltyStage:
    """`game.novelty_ctx`: novidade do jogo com a mediana móvel dentro de cada contexto.

    Contexto com pouco tempo de áudio (ou sem contexto) mantém a `novelty` da sessão inteira, com aviso.
    """

    name = "context_novelty"
    version = "1"
    needs: tuple[str, ...] = ("audio_signals", "video_contexts")
    uses_gpu = False

    def __init__(self, min_context_s: float = 120.0) -> None:
        self.min_context_s = min_context_s
        self.dsp = dsp.DspParams(hop_frames=AUDIO_HOP)

    def params(self, settings: Settings) -> dict[str, Any]:
        return {**self.dsp.as_dict(), "min_context_s": self.min_context_s}

    def run(self, ctx: StageContext) -> StageResult:
        audio = signal_metas(ctx.inputs["audio_signals"])
        video = signal_metas(ctx.inputs["video_contexts"])
        onset = np.asarray(load_signal(audio["game.onset"]).values, dtype=np.float32)
        session = np.asarray(load_signal(audio["game.novelty"]).values, dtype=np.float32)
        labels = np.asarray(load_signal(video["video.context"]).values).astype(np.int32)
        per_sample = np.minimum(np.arange(len(onset)) * AUDIO_HOP // EMBED_HOP, max(len(labels) - 1, 0))
        sample_ctx = labels[per_sample] if len(labels) else np.full(len(onset), NO_CONTEXT, np.int32)
        out = session.copy()
        warnings: list[str] = []
        min_samples = int(self.min_context_s * self.dsp.per_second)
        for cid in np.unique(sample_ctx):
            if cid == NO_CONTEXT:
                continue
            idx = np.flatnonzero(sample_ctx == cid)
            if len(idx) < min_samples:
                warnings.append(
                    f"contexto {cid} com {len(idx) / self.dsp.per_second:.0f} s de áudio: usa a sessão"
                )
                continue
            out[idx] = dsp.novelty(onset[idx], self.dsp)
        meta: SignalMeta = write_signal(
            ctx.out_dir,
            "game.novelty_ctx",
            out,
            unit="desvios",
            source_track="game",
            version=self.version,
            params=self.params(ctx.settings),
            hop_frames=AUDIO_HOP,
            model="dsp",
        )
        return StageResult(
            files=[meta.path], data={SIGNALS_KEY: {"game.novelty_ctx": meta.model_dump()}}, warnings=warnings
        )


class BrollStage:
    """Biblioteca de B-roll: eventos `broll` (câmera parada/panorâmica) com utilidade, tags e capa."""

    name = "video_broll"
    version = "5"
    uses_gpu = True  # o encoder de texto roda no modelo carregado na GPU: passa pelo gate

    def __init__(
        self, embedder: FrameEmbedder, params: BrollParams | None = None, *, with_hud_text: bool = False
    ) -> None:
        self.embedder = embedder
        self.broll = params or BrollParams()
        self.with_hud_text = with_hud_text
        self.needs: tuple[str, ...] = ("video_scenes", "video_embeddings", "video_hud") + (
            ("video_hud_text",) if with_hud_text else ()
        )

    def params(self, settings: Settings) -> dict[str, Any]:
        e = self.embedder
        return {
            **self.broll.__dict__,
            "embedder": [e.name, e.version, e.options],
            "hud_text": self.with_hud_text,
        }

    def run(self, ctx: StageContext) -> StageResult:
        scenes = events_from_result(ctx.inputs["video_scenes"]) or []
        emb = np.asarray(load_embeddings(ctx.inputs["video_embeddings"]), dtype=np.float32)
        huds = events_from_result(ctx.inputs["video_hud"]) or []
        texts = events_from_result(ctx.inputs["video_hud_text"]) or [] if self.with_hud_text else []
        has_hud = bool(ctx.inputs["video_hud"].data.get(HAS_HUD_KEY, False))
        digest = params_hash(self.params(ctx.settings))
        events: list[AnalysisEvent] = []
        bank = text_bank(self.embedder)
        for c in candidates(scenes, self.broll):
            info = score_candidate(emb, bank, self.broll, hop=EMBED_HOP, c=c)
            if info is None:
                continue
            info["hud"] = hud_state(c, huds, has_hud)
            info["tags"] = [*info["tags"], *theme_tags(c, texts)]
            events.append(
                AnalysisEvent(
                    kind="broll",
                    evidence=Evidence(
                        source=EvidenceSource.CENA,
                        start_frame=c.start_frame,
                        end_frame=c.end_frame,
                        confidence=float(info["utilidade"]),
                        model=self.embedder.name,
                        model_version=self.embedder.version,
                        params_hash=digest,
                    ),
                    payload=info,
                )
            )
        path = write_events_file(ctx.out_dir, events)
        return StageResult(files=[str(path)], data={EVENTS_KEY: path, "count": len(events)})

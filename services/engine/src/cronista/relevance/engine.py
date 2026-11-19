"""Motor de relevância (Fase 4): fusão de sinais → segmentação → classificação → nota explicável.

Tudo em segundos inteiros (grade de 1 s) sobre eventos já gravados (fala, risada, exclamação, menu, loading,
idle, contexto) e marcadores; funções puras, sem banco, GPU nem modelo, então rodam em `dev`. Nenhuma regra
por jogo: os pesos vivem em `RelevanceParams` (perfil genérico, a calibrar com o gabarito).

Cada segmento sai com `razoes`: as contribuições da nota, para o criador ver por que ele subiu ou desceu.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import numpy.typing as npt

from cronista.domain.evidence import AnalysisEvent
from cronista.domain.frames import FPS

FloatArray = npt.NDArray[np.float64]

SCREEN_PAUSE = ("menu", "loading", "idle")
EMOTION = ("risada", "exclamacao", "grito")
MARKER_WEIGHT: dict[str, float] = {
    "momento": 1.0,
    "conquista": 0.9,
    "engracado": 0.8,
    "morte_falha": 0.7,
    "cinematica": 0.6,
    "novo_dia": 0.5,
    "construcao": 0.4,
    "foto_progresso": 0.3,
}
"""Peso de cada tipo de marcador na nota (tocar uma tecla já é um voto do criador)."""
TIMELAPSE_FACTOR = 10.0
MAX_KEPT_S = 45.0
MAX_FARM_S = 20.0
DEFAULT_LOOKBACK_S = 20.0


@dataclass(frozen=True)
class RelevanceParams:
    snap_s: float = 8.0
    """Raio para encostar a borda do trecho de um marcador numa fronteira natural (fala, mudança de cena)."""
    min_s: int = 8
    max_s: int = 180
    pause_frac: float = 0.6
    """Fração do trecho em menu/loading/idle a partir da qual ele é descartável."""
    farm_speech: float = 0.15
    farm_min_s: int = 60
    talk_speech: float = 0.5
    momento_score: float = 0.55
    keep_score: float = 0.35
    w_marker: float = 0.5
    w_emotion: float = 0.2
    w_speech: float = 0.15
    w_novelty: float = 0.15
    w_pause: float = 0.5
    speech_gap_s: int = 4
    """Silêncio que separa dois blocos de fala."""
    tail_s: float = 8.0
    """Quanto depois do toque o trecho do marcador termina."""
    lookback_momento: float = 25.0
    lookback_engracado: float = 20.0
    lookback_conquista: float = 20.0
    lookback_morte_falha: float = 30.0
    lookback_cinematica: float = 5.0
    lookback_novo_dia: float = 5.0
    lookback_construcao: float = 5.0
    lookback_foto_progresso: float = 5.0
    """Quanto antes do toque o trecho do marcador começa (o criador aperta depois de o momento acontecer).
    Ajustável por perfil (grupo `relevance`); um tipo de marcador sem campo usa `DEFAULT_LOOKBACK_S`."""

    def lookback(self, kind: str) -> float:
        value = getattr(self, f"lookback_{kind}", None)
        return float(value) if isinstance(value, float) else DEFAULT_LOOKBACK_S


SegmentClass = Literal["descartavel", "dia", "momento", "farm", "conversa", "jogo"]
"""Classes de um trecho: único lugar que as lista (API, pacote da história e Studio usam este tipo)."""


@dataclass
class Segment:
    start_s: int
    end_s: int
    classe: str
    score: float
    razoes: list[str] = field(default_factory=list)
    markers: list[str] = field(default_factory=list)
    features: dict[str, float] = field(default_factory=dict)

    @property
    def duration_s(self) -> int:
        return self.end_s - self.start_s


def is_kept(seg: Segment, keep_score: float = RelevanceParams.keep_score) -> bool:
    """Critério único de "material mantido" (painel, arco, qualidade).

    Vale nota >= `keep_score`, farm, dia ou trecho com marcador (o voto do criador). Descartável nunca.
    """
    if seg.classe == "descartavel":
        return False
    return seg.classe in ("farm", "dia") or seg.score >= keep_score or bool(seg.markers)


def kept_seconds(seg: Segment, keep_score: float = RelevanceParams.keep_score) -> float:
    """Segundos que o segmento deve ocupar no vídeo: farm em timelapse, o resto limitado a `MAX_KEPT_S`."""
    if not is_kept(seg, keep_score):
        return 0.0
    if seg.classe == "farm":
        return min(seg.duration_s / TIMELAPSE_FACTOR, MAX_FARM_S)
    return min(float(seg.duration_s), MAX_KEPT_S)


@dataclass(frozen=True)
class MarkerRef:
    marker_id: str
    kind: str
    second: float


def _sec(frame: int) -> float:
    return frame / FPS


def _cover(
    n: int, events: Sequence[AnalysisEvent], kinds: Sequence[str], weight_conf: bool = False
) -> FloatArray:
    """Fração de cada segundo coberta pelos eventos dos `kinds` (pontual vale o segundo em que está)."""
    out = np.zeros(n, dtype=np.float64)
    for e in events:
        if e.kind not in kinds:
            continue
        a, b = _sec(e.evidence.start_frame), _sec(e.evidence.end_frame)
        b = max(b, a + 1e-3)
        w = e.evidence.confidence if weight_conf else 1.0
        for s in range(max(int(a), 0), min(math.ceil(b), n)):
            out[s] += max(0.0, min(b, s + 1) - max(a, s)) * w
    return np.minimum(out, 1.0)


def _runs(mask: npt.NDArray[np.bool_]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    i = 0
    while i < len(mask):
        if mask[i]:
            j = i
            while j < len(mask) and mask[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def speech_blocks(speech: FloatArray, gap_s: int) -> list[tuple[int, int]]:
    """Blocos de fala contínua: lacunas de até `gap_s` segundos não quebram o bloco."""
    blocks: list[tuple[int, int]] = []
    for a, b in _runs(speech >= 0.3):
        if blocks and a - blocks[-1][1] <= gap_s:
            blocks[-1] = (blocks[-1][0], b)
        else:
            blocks.append((a, b))
    return blocks


def _snap(t: float, anchors: Sequence[int], radius: float) -> int:
    near = [a for a in anchors if abs(a - t) <= radius]
    return min(near, key=lambda a: abs(a - t)) if near else round(t)


def marker_window(
    marker: MarkerRef,
    anchors_start: Sequence[int],
    anchors_end: Sequence[int],
    n: int,
    params: RelevanceParams,
) -> tuple[int, int]:
    """Janela do trecho de um marcador: lookback por tipo, depois encostada nas fronteiras naturais."""
    start = _snap(marker.second - params.lookback(marker.kind), anchors_start, params.snap_s)
    end = _snap(marker.second + params.tail_s, anchors_end, params.snap_s)
    start = max(0, min(start, int(marker.second)))
    end = min(n, max(end, math.ceil(marker.second) + 1))
    return start, end


def _merge_windows(
    wins: list[tuple[int, int, list[str]]], max_s: int, boundary_ids: frozenset[str] = frozenset()
) -> list[tuple[int, int, list[str]]]:
    """Junta janelas de marcador que se sobrepõem, sem passar de `max_s` e sem atravessar um `novo_dia`.

    Quando não pode juntar, divide no ponto de encontro: o marcador de fronteira (`boundary_ids`) mantém o
    início do seu próprio trecho, e o resto fica com o que sobra. Janela inteira dentro da anterior só entrega
    os ids.
    """
    out: list[tuple[int, int, list[str]]] = []
    for a, b, ids in sorted(wins):
        if not out or a > out[-1][1]:
            out.append((a, b, list(ids)))
            continue
        pa, pb, pids = out[-1]
        new_edge = bool(boundary_ids.intersection(ids))
        old_edge = bool(boundary_ids.intersection(pids))
        if not new_edge and not old_edge and max(pb, b) - pa <= max_s:
            out[-1] = (pa, max(pb, b), pids + ids)
        elif new_edge and a > pa:
            out[-1] = (pa, a, pids)  # o `novo_dia` começa o trecho dele; o anterior termina ali
            out.append((a, b, list(ids)))
        elif b <= pb:
            out[-1] = (pa, pb, pids + ids)  # inteira dentro da anterior: só entrega os ids
        else:
            out.append((pb, b, list(ids)))  # começa onde a anterior termina
    return out


def _split_free(
    a: int,
    b: int,
    regime: npt.NDArray[np.int_],
    ctx_starts: set[int],
    speech: FloatArray,
    params: RelevanceParams,
) -> list[tuple[int, int]]:
    """Corta um trecho livre onde o regime (jogo x pausa) ou o contexto muda, e onde passa de `max_s`."""
    cuts = [a]
    for s in range(a + 1, b):
        if regime[s] != regime[s - 1] or s in ctx_starts:
            cuts.append(s)
    cuts.append(b)
    pieces = [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)]
    out: list[tuple[int, int]] = []
    for pa, pb in pieces:
        while pb - pa > params.max_s:
            lo, hi = pa + params.max_s // 2, pa + params.max_s
            cut = lo + int(np.argmin(speech[lo:hi])) if hi > lo else hi
            out.append((pa, cut))
            pa = cut
        out.append((pa, pb))
    # junta pedaços curtos demais ao vizinho
    merged: list[tuple[int, int]] = []
    for pa, pb in out:
        if merged and (pb - pa < params.min_s or merged[-1][1] - merged[-1][0] < params.min_s):
            merged[-1] = (merged[-1][0], pb)
        else:
            merged.append((pa, pb))
    return merged


def build_segments(
    events: Sequence[AnalysisEvent],
    markers: Sequence[MarkerRef],
    duration_s: float | None = None,
    params: RelevanceParams | None = None,
) -> list[Segment]:
    """Segmenta o arquivo todo, classifica e dá nota explicável a cada segmento (ordem do tempo)."""
    params = params or RelevanceParams()
    ends = [_sec(e.evidence.end_frame) for e in events] + [m.second + params.tail_s for m in markers]
    n = math.ceil(duration_s if duration_s is not None else max(ends, default=0.0))
    if n <= 0:
        return []
    speech = _cover(n, events, ("fala",))
    emotion = _cover(n, events, EMOTION, weight_conf=True)
    pause_by_kind = {k: _cover(n, events, (k,)) for k in SCREEN_PAUSE}
    pause = np.maximum.reduce(list(pause_by_kind.values()))
    paused = pause >= 0.5
    ctx_events = sorted((e for e in events if e.kind == "contexto"), key=lambda e: e.evidence.start_frame)
    ctx_starts = {int(_sec(e.evidence.start_frame)) for e in ctx_events}
    first_seen: dict[object, int] = {}
    for e in ctx_events:
        first_seen.setdefault(e.payload.get("context_id"), int(_sec(e.evidence.start_frame)))
    novel_starts = set(first_seen.values())

    blocks = speech_blocks(speech, params.speech_gap_s)
    regime = np.where(paused, 2, 0)  # 2 = menu/loading/idle, 1 = dentro de um bloco de fala, 0 = jogo calado
    for ba, bb in blocks:
        regime[ba:bb] = np.where(paused[ba:bb], 2, 1)
    anchors_start = sorted({a for a, _ in blocks} | ctx_starts | {b for _, b in _runs(paused)})
    anchors_end = sorted({b for _, b in blocks} | ctx_starts | {a for a, _ in _runs(paused)})

    forced = _merge_windows(
        [(*marker_window(m, anchors_start, anchors_end, n, params), [m.marker_id]) for m in markers],
        params.max_s,
        frozenset(m.marker_id for m in markers if m.kind == "novo_dia"),
    )
    spans: list[tuple[int, int, list[str]]] = list(forced)
    cursor = 0
    for fa, fb, _ in [*forced, (n, n, [])]:
        if fa > cursor:
            spans += [(a, b, []) for a, b in _split_free(cursor, fa, regime, ctx_starts, speech, params)]
        cursor = max(cursor, fb)
    spans.sort()

    kind_of = {m.marker_id: m.kind for m in markers}
    out = [
        _score(a, b, ids, kind_of, speech, emotion, pause, pause_by_kind, novel_starts, params)
        for a, b, ids in spans
        if b > a
    ]
    return out


def _score(
    a: int,
    b: int,
    ids: list[str],
    kind_of: dict[str, str],
    speech: FloatArray,
    emotion: FloatArray,
    pause: FloatArray,
    pause_by_kind: dict[str, FloatArray],
    novel_starts: set[int],
    p: RelevanceParams,
) -> Segment:
    length = b - a
    sp = float(speech[a:b].mean())
    em_peak = float(emotion[a:b].max()) if length else 0.0
    em_count = len(_runs(emotion[a:b] >= 0.2))
    em = min(1.0, em_peak * 0.6 + 0.2 * min(em_count, 2))
    pa = float(pause[a:b].mean())
    kinds = sorted({kind_of[i] for i in ids})
    mk = max((MARKER_WEIGHT.get(k, 0.3) for k in kinds), default=0.0)
    novel = 1.0 if any(a <= s < b for s in novel_starts) else 0.0
    parts = {
        "marcador": p.w_marker * mk,
        "emocao": p.w_emotion * em,
        "fala": p.w_speech * sp,
        "novidade": p.w_novelty * novel,
    }
    penalty = p.w_pause * pa
    score = max(
        0.0,
        min(1.0, sum(parts.values()) / (p.w_marker + p.w_emotion + p.w_speech + p.w_novelty) * 1.6 - penalty),
    )
    reasons = [f"{k} +{v:.2f}" for k, v in parts.items() if v > 0.005]
    if kinds:
        reasons.insert(0, "marcadores: " + ", ".join(kinds))
    if penalty > 0.005:
        reasons.append(f"menu/loading/idle -{penalty:.2f}")

    if pa >= p.pause_frac and not kinds:  # o voto do criador (marcador) nunca perde para o descarte
        dominant = max(pause_by_kind, key=lambda k: float(pause_by_kind[k][a:b].sum()))
        classe = "descartavel"
        reasons.append(f"tela dominante: {dominant}")
    elif "novo_dia" in kinds and score < p.momento_score:
        classe = "dia"
    elif kinds or score >= p.momento_score:
        classe = "momento"
    elif sp < p.farm_speech and em < 0.2 and length >= p.farm_min_s:
        classe = "farm"
        reasons.append(f"pouca fala ({sp:.0%}) por {length}s sem emoção")
    elif sp >= p.talk_speech:
        classe = "conversa"
    else:
        classe = "jogo"
    return Segment(
        a, b, classe, round(score, 3), reasons, ids,
        {"fala": round(sp, 3), "emocao": round(em, 3), "pausa": round(pa, 3), "marcador": mk,
         "novidade": novel},
    )  # fmt: skip

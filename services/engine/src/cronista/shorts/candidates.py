"""Candidatos a Shorts (Fase 6D): janelas de até 13 s com o gancho nos 3 primeiros segundos (plano 6.6).

Puro e determinístico. Só escolhe e justifica janelas; reenquadramento 9:16, legenda e margens são da Fase 9.
Pico = marcador do criador (voto dele) ou a emoção mais confiante do trecho; sem pico, não há candidato.
O gancho é o primeiro ponto de interesse: início de fala depois de silêncio, emoção ou o próprio pico.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

from cronista.assembly.plan import WordSpan
from cronista.domain.frames import FPS
from cronista.relevance.engine import Segment

MAX_S = 13.0
HOOK_S = 3.0


@dataclass(frozen=True)
class ShortsParams:
    max_s: float = MAX_S
    min_s: float = 5.0
    hook_s: float = HOOK_S
    post_s: float = 4.0
    """Quanto depois do pico a janela segue (a reação)."""
    min_score: float = 0.5
    max_candidates: int = 10
    lead_s: float = 0.5
    """Folga antes do gancho quando a janela é recuada para ele."""
    quiet_s: float = 1.0
    """Silêncio mínimo para uma fala contar como começo novo (gancho)."""


@dataclass(frozen=True)
class Emotion:
    start_frame: int
    end_frame: int
    confidence: float


@dataclass(frozen=True)
class SpeechUtterance:
    start_frame: int
    end_frame: int
    words: tuple[WordSpan, ...] = ()


@dataclass(frozen=True)
class FileMaterial:
    """Tudo de um arquivo que o candidato precisa, em quadros (segmentos em segundos, como na Fase 4)."""

    file_id: int
    segments: Sequence[Segment]
    marker_frames: Mapping[str, int]
    emotions: Sequence[Emotion] = ()
    speech: Sequence[SpeechUtterance] = ()


@dataclass(frozen=True)
class ShortCandidate:
    file_id: int
    start_frame: int
    end_frame: int
    peak_frame: int
    hook_frame: int
    hook_kind: str
    score: float
    reason: str
    segment_start_s: int

    @property
    def duration_s(self) -> float:
        return (self.end_frame - self.start_frame) / FPS

    @property
    def hook_offset_s(self) -> float:
        return (self.hook_frame - self.start_frame) / FPS


def _peak(seg: Segment, mat: FileMaterial) -> tuple[int, str] | None:
    frames = [mat.marker_frames[m] for m in seg.markers if m in mat.marker_frames]
    if frames:
        return min(frames), "marcador"
    lo, hi = seg.start_s * FPS, seg.end_s * FPS
    inside = [e for e in mat.emotions if lo <= e.start_frame < hi]
    if not inside:
        return None
    best = max(inside, key=lambda e: (e.confidence, -e.start_frame))
    return best.start_frame, "emocao"


def _hooks(mat: FileMaterial, peak: tuple[int, str], lo: int, hi: int, quiet: int) -> list[tuple[int, str]]:
    """Pontos de interesse em `[lo, hi]`: fala após silêncio (ou em curso em `lo`), emoção e o pico."""
    points: list[tuple[int, str]] = []
    previous_end: int | None = None
    for u in sorted(mat.speech, key=lambda s: s.start_frame):
        if lo <= u.start_frame <= hi and (previous_end is None or u.start_frame - previous_end >= quiet):
            points.append((u.start_frame, "fala"))
        elif u.start_frame < lo <= u.end_frame:
            points.append((lo, "fala"))
        previous_end = u.end_frame
    points += [(e.start_frame, "emocao") for e in mat.emotions if lo <= e.start_frame <= hi]
    if lo <= peak[0] <= hi:
        points.append((peak[0], peak[1]))
    return sorted(points)


def _snap_start(frame: int, words: Sequence[WordSpan], limit: int) -> int:
    for w in words:
        if w.start_frame < frame < w.end_frame:
            return w.start_frame if frame - w.start_frame <= limit else w.end_frame
    return frame


def _snap_end(frame: int, words: Sequence[WordSpan], limit: int, ceiling: int) -> int:
    """Tira o fim de dentro de uma palavra: ao fim dela se perto e até `ceiling`; senão, ao começo."""
    for w in words:
        if w.start_frame < frame < w.end_frame:
            return w.end_frame if w.end_frame - frame <= limit and w.end_frame <= ceiling else w.start_frame
    return frame


def candidates_for_file(mat: FileMaterial, params: ShortsParams) -> list[ShortCandidate]:
    words = sorted((w for u in mat.speech for w in u.words), key=lambda w: w.start_frame)
    max_f, min_f, hook_f = round(params.max_s * FPS), round(params.min_s * FPS), round(params.hook_s * FPS)
    limit = FPS // 2
    out: list[ShortCandidate] = []
    for seg in mat.segments:
        if seg.classe not in ("momento", "dia") or seg.score < params.min_score:
            continue
        peak = _peak(seg, mat)
        if peak is None:
            continue
        seg_lo, seg_hi = seg.start_s * FPS, seg.end_s * FPS
        end = min(seg_hi, peak[0] + round(params.post_s * FPS))
        lead = round(params.lead_s * FPS)
        # o gancho é o primeiro ponto de interesse que ainda deixa a janela caber em `max_s`
        hooks = _hooks(mat, peak, max(seg_lo, end - max_f + lead), peak[0], round(params.quiet_s * FPS))
        if not hooks:
            continue
        hook_frame, hook_kind = hooks[0]
        start = _snap_start(max(seg_lo, hook_frame - lead), words, limit)
        end = min(seg_hi, max(end, start + min_f))  # reação curta demais: estende até o mínimo
        end = min(end, start + max_f)
        end = _snap_end(end, words, limit, ceiling=start + max_f)
        if end - start < min_f or end - start > max_f or not (start <= hook_frame <= start + hook_f):
            continue
        out.append(
            ShortCandidate(
                file_id=mat.file_id,
                start_frame=start,
                end_frame=end,
                peak_frame=peak[0],
                hook_frame=hook_frame,
                hook_kind=hook_kind,
                score=seg.score,
                reason="; ".join(seg.razoes[:3]) or seg.classe,
                segment_start_s=seg.start_s,
            )
        )
    return out


def pick_candidates(
    materials: Sequence[FileMaterial], params: ShortsParams | None = None
) -> list[ShortCandidate]:
    """Os melhores candidatos de todos os arquivos, sem sobreposição, do maior para o menor score."""
    p = params or ShortsParams()
    pool = [c for m in materials for c in candidates_for_file(m, p)]
    pool.sort(key=lambda c: (-c.score, c.file_id, c.start_frame))
    chosen: list[ShortCandidate] = []
    for c in pool:
        if any(
            k.file_id == c.file_id and c.start_frame < k.end_frame and k.start_frame < c.end_frame
            for k in chosen
        ):
            continue
        chosen.append(c)
        if len(chosen) >= p.max_candidates:
            break
    return chosen


def to_json(candidates: Sequence[ShortCandidate]) -> str:
    rows = [
        asdict(c) | {"duracao_s": round(c.duration_s, 2), "gancho_em_s": round(c.hook_offset_s, 2)}
        for c in candidates
    ]
    return json.dumps({"fps": FPS, "candidatos": rows}, ensure_ascii=False, indent=1)

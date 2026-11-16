"""Janelas da prévia MP4: um trecho ao redor de cada marcador (plano da 1B, tarefa 5).

Sem lookback inteligente (isso é da Fase 4): a janela é fixa, `pre_s` antes e `post_s` depois, recortada
aos limites do arquivo. Um marcador, um trecho: janelas que se sobrepõem não são fundidas.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from cronista.domain.models import MarkerKind

MIN_CLIP_S = 0.5
"""Trecho menor que isso não vale a pena (marcador colado ou além do fim do arquivo)."""


@dataclass(frozen=True)
class MarkerPoint:
    """Marcador já com tempo de mídia final; `file_id` identifica o master de onde sai o trecho."""

    marker_id: str
    kind: MarkerKind
    file_id: int
    time_s: float
    file_duration_s: float | None


@dataclass(frozen=True)
class ClipWindow:
    marker_id: str
    kind: MarkerKind
    file_id: int
    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


def plan_windows(
    points: Sequence[MarkerPoint], pre_s: float, post_s: float
) -> tuple[list[ClipWindow], list[str]]:
    """Uma janela por marcador, na ordem recebida. Devolve também os avisos (trechos descartados)."""
    windows: list[ClipWindow] = []
    warnings: list[str] = []
    for point in points:
        start = max(0.0, point.time_s - pre_s)
        end = point.time_s + post_s
        if point.file_duration_s is not None:
            end = min(end, point.file_duration_s)
        if end - start < MIN_CLIP_S:
            warnings.append(
                f"marcador {point.kind.value}|{point.marker_id} @ {point.time_s:.1f}s fora do arquivo "
                "ou sem trecho utilizável: ficou de fora da prévia"
            )
            continue
        windows.append(ClipWindow(point.marker_id, point.kind, point.file_id, start, end))
    return windows, warnings


def expected_duration_s(windows: Sequence[ClipWindow]) -> float:
    return sum(w.duration_s for w in windows)

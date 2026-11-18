"""Tempo em quadros inteiros a 60 fps (lacuna técnica 1 do plano, histórico §36).

Toda gravação, timeline e render do Cronista é 60 fps exatos (CLAUDE.md), então o tempo de um marcador cabe
num inteiro: o quadro de mídia dentro do arquivo. Segundos só existem nas bordas (ffprobe, FFmpeg, texto de
aviso), sempre convertidos por estas funções para o arredondamento ser um só.
"""

from __future__ import annotations

import math

FPS = 60


def seconds_to_frame(seconds: float) -> int:
    """Quadro mais próximo do instante, nunca negativo (o arredondamento é ao quadro, não para baixo)."""
    return max(0, round(seconds * FPS))


def frame_to_seconds(frame: int) -> float:
    return frame / FPS


def duration_frames(duration_s: float) -> int:
    """Duração em quadros, **para baixo**: nunca passa do último quadro real do arquivo."""
    return max(0, math.floor(duration_s * FPS))


def fcpxml_time(frames: float) -> str:
    """Tempo racional do FCPXML (`<quadros>/60s`): sempre um número inteiro de quadros."""
    return f"{round(frames)}/{FPS}s"

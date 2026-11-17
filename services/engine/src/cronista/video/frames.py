"""Leitura de quadros amostrados do proxy, em tons de cinza e baixa resolução, em blocos (Fase 3A).

Memória constante: o FFmpeg entrega os quadros por pipe e só um bloco fica na memória. O quadro amostrado `i`
corresponde ao quadro `i * hop_frames` a 60 fps (aritmética inteira, histórico §38); a 5 fps o hop é 12.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import numpy.typing as npt

from cronista.config import Settings
from cronista.domain.frames import FPS
from cronista.pipeline.stage import StageError

SAMPLE_FPS = 5
HOP_FRAMES = FPS // SAMPLE_FPS
"""Quadros a 60 fps entre duas amostras: 12 (5 por segundo)."""

WIDTH, HEIGHT = 160, 90
BLOCK_SAMPLES = 1500
"""Amostras por bloco (5 min a 5 fps, 21 MB em 160x90)."""

GrayFrames = npt.NDArray[np.uint8]


def iter_gray_blocks(
    settings: Settings,
    video: Path,
    *,
    sample_fps: int = SAMPLE_FPS,
    width: int = WIDTH,
    height: int = HEIGHT,
    block: int = BLOCK_SAMPLES,
    between_blocks: Callable[[], None] = lambda: None,
) -> Iterator[GrayFrames]:
    """Blocos `(n, altura, largura)` de quadros em cinza, a `sample_fps`, do começo ao fim do vídeo."""
    if FPS % sample_fps:
        raise ValueError(f"sample_fps={sample_fps} precisa dividir {FPS}")
    cmd = [
        settings.ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(video),
        "-an", "-vf", f"fps={sample_fps},scale={width}:{height}:flags=area,format=gray",
        "-f", "rawvideo", "-",
    ]  # fmt: skip
    size = width * height
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None
    try:
        while True:
            between_blocks()
            data = proc.stdout.read(size * block)
            usable = len(data) // size * size
            if usable:
                yield np.frombuffer(data[:usable], dtype=np.uint8).reshape(-1, height, width)
            if len(data) < size * block:  # fim do fluxo (o pipe só devolve menos no EOF)
                break
    finally:
        proc.stdout.close()
        stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        code = proc.wait()
        if proc.stderr:
            proc.stderr.close()
    if code != 0:
        raise StageError(f"ffmpeg falhou ({code}) ao ler quadros: {stderr.strip()[-500:]}")

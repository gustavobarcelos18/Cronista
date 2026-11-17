"""Leitura de quadros amostrados do proxy, em tons de cinza e baixa resolução, em blocos (Fase 3A).

Memória constante: o FFmpeg entrega os quadros por pipe e só um bloco fica na memória. O quadro amostrado `i`
corresponde ao quadro `i * hop_frames` a 60 fps (aritmética inteira, histórico §38); a 5 fps o hop é 12.
"""

from __future__ import annotations

import subprocess
import tempfile
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
    for data in _iter_raw(settings, video, sample_fps, width, height, "gray", 1, block, between_blocks):
        yield data.reshape(-1, height, width)


def iter_rgb_blocks(
    settings: Settings,
    video: Path,
    *,
    sample_fps: int = 1,
    size: int = 224,
    block: int = 64,
    between_blocks: Callable[[], None] = lambda: None,
) -> Iterator[npt.NDArray[np.uint8]]:
    """Blocos `(n, size, size, 3)` RGB, a `sample_fps`, esticados para o quadrado que o modelo espera."""
    for data in _iter_raw(settings, video, sample_fps, size, size, "rgb24", 3, block, between_blocks):
        yield data.reshape(-1, size, size, 3)


def _iter_raw(
    settings: Settings,
    video: Path,
    sample_fps: int,
    width: int,
    height: int,
    pix_fmt: str,
    channels: int,
    block: int,
    between_blocks: Callable[[], None],
) -> Iterator[npt.NDArray[np.uint8]]:
    if FPS % sample_fps:
        raise ValueError(f"sample_fps={sample_fps} precisa dividir {FPS}")
    cmd = [
        settings.ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(video),
        "-an", "-vf", f"fps={sample_fps},scale={width}:{height}:flags=area,format={pix_fmt}",
        "-f", "rawvideo", "-",
    ]  # fmt: skip
    size = width * height * channels
    # stderr em arquivo: um pipe que ninguém drena enche (64 KB) e trava o ffmpeg com o stdout parado.
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err)
        assert proc.stdout is not None
        try:
            while True:
                between_blocks()
                data = proc.stdout.read(size * block)
                usable = len(data) // size * size
                if usable:
                    yield np.frombuffer(data[:usable], dtype=np.uint8)
                if len(data) < size * block:  # fim do fluxo (o pipe só devolve menos no EOF)
                    break
        finally:
            proc.stdout.close()
            code = proc.wait()
        if code != 0:
            err.seek(0)
            stderr = err.read().decode(errors="replace")
            raise StageError(f"ffmpeg falhou ({code}) ao ler quadros: {stderr.strip()[-500:]}")


def iter_frames_every(
    settings: Settings,
    video: Path,
    *,
    every_s: float,
    width: int = 1280,
    height: int = 720,
    start_s: float = 0.0,
    end_s: float | None = None,
) -> Iterator[tuple[float, npt.NDArray[np.uint8]]]:
    """`(segundo, quadro RGB (altura, largura, 3))` a cada `every_s` segundos, de `start_s` até `end_s`.

    Para o OCR do HUD: lê o **master** (no proxy 360p o texto fica ilegível), um quadro por vez.
    """
    if every_s <= 0:
        raise ValueError("every_s precisa ser positivo")
    cmd = [settings.ffmpeg, "-hide_banner", "-loglevel", "error"]
    if start_s > 0:
        cmd += ["-ss", f"{start_s:.3f}"]
    if end_s is not None:
        cmd += ["-t", f"{max(end_s - start_s, 0):.3f}"]
    cmd += [
        "-i", str(video), "-an",
        "-vf", f"fps=1/{every_s:g},scale={width}:{height}:flags=area,format=rgb24",
        "-f", "rawvideo", "-",
    ]  # fmt: skip
    size = width * height * 3
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err)
        assert proc.stdout is not None
        index = 0
        try:
            while True:
                data = proc.stdout.read(size)
                if len(data) < size:
                    break
                yield start_s + index * every_s, np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3)
                index += 1
        finally:
            proc.stdout.close()
            code = proc.wait()
        if code != 0:
            err.seek(0)
            detail = err.read().decode(errors="replace").strip()[-500:]
            raise StageError(f"ffmpeg falhou ({code}) ao ler o master: {detail}")

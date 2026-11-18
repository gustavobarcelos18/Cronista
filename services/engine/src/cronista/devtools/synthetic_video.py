"""Vídeo sintético com verdade de campo para testar a análise visual em qualquer máquina (sem jogo, sem GPU).

Segmentos, em 5 quadros por segundo: jogabilidade (textura deslizando com ruído), loading (tela escura com uma
barrinha), menu (tela parada cheia de linhas de texto, com um cursor) e idle (cena parada e lisa).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from cronista.config import Settings

FPS = 5
WIDTH, HEIGHT = 320, 180

Frames = npt.NDArray[np.uint8]


@dataclass(frozen=True)
class Truth:
    kind: str  # gameplay | loading | menu | idle
    start_s: float
    end_s: float


def _gameplay(n: int, rng: np.random.Generator, offset: int) -> Frames:
    texture = rng.integers(40, 200, size=(HEIGHT // 4, WIDTH * 3 // 4), dtype=np.uint8)
    wide = np.kron(texture, np.ones((4, 4), dtype=np.uint8))
    out = np.empty((n, HEIGHT, WIDTH), dtype=np.uint8)
    for i in range(n):
        shifted = np.roll(wide, -(offset + i) * 9, axis=1)[:, :WIDTH]
        noise = rng.integers(-6, 7, size=shifted.shape)
        out[i] = np.clip(shifted.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    return out


def _loading(n: int) -> Frames:
    out = np.full((n, HEIGHT, WIDTH), 4, dtype=np.uint8)
    for i in range(n):
        out[i, HEIGHT - 20 : HEIGHT - 14, 20 : 20 + 4 * (i + 1)] = 160
    return out


def _menu(n: int, rng: np.random.Generator) -> Frames:
    base = np.full((HEIGHT, WIDTH), 50, dtype=np.uint8)
    for row in range(8, HEIGHT - 8, 10):
        width = int(rng.integers(120, WIDTH - 40))
        base[row : row + 5, 20 : 20 + width] = 230
    out = np.repeat(base[None], n, axis=0)
    for i in range(n):
        out[i, 20:30, 280 + (i % 3) * 8 : 288 + (i % 3) * 8] = 255  # cursor
    return out


def _idle(n: int, rng: np.random.Generator) -> Frames:
    ramp = np.tile(np.linspace(90, 130, WIDTH, dtype=np.float32), (HEIGHT, 1))
    out = np.empty((n, HEIGHT, WIDTH), dtype=np.uint8)
    for i in range(n):
        out[i] = np.clip(ramp + rng.integers(-1, 2, size=ramp.shape), 0, 255).astype(np.uint8)
    return out


def build(seed: int = 7) -> tuple[Frames, list[Truth]]:
    rng = np.random.default_rng(seed)
    plan = [("gameplay", 30), ("loading", 20), ("menu", 25), ("idle", 40), ("gameplay", 30)]
    parts: list[Frames] = []
    truth: list[Truth] = []
    cursor = 0
    for kind, n in plan:
        if kind == "gameplay":
            parts.append(_gameplay(n, rng, cursor))
        elif kind == "loading":
            parts.append(_loading(n))
        elif kind == "menu":
            parts.append(_menu(n, rng))
        else:
            parts.append(_idle(n, rng))
        truth.append(Truth(kind, cursor / FPS, (cursor + n) / FPS))
        cursor += n
    return np.concatenate(parts), truth


def write_video(settings: Settings, path: Path, frames: Frames) -> None:
    """Codifica os quadros cinza em MP4 H.264 (qualidade alta, para os detalhes finos sobreviverem)."""
    import subprocess

    from cronista.media.ffmpeg import ffmpeg_cmd

    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ffmpeg_cmd(
        settings,
        [
            "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12", "-pix_fmt", "yuv420p", str(path),
        ],
    )  # fmt: skip
    proc = subprocess.run(cmd, input=frames.tobytes(), capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors="replace")[-500:])

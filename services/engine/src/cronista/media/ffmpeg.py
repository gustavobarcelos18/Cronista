"""FFmpeg num único lugar: linha de comando base, execução, leitura de quadros brutos e encoder.

Só este módulo monta o começo da linha de comando (`ffmpeg -hide_banner -loglevel ... -y`) e trata o código de
saída e o `stderr`. Tempo em quadros sempre vem de `domain.frames`, para o `-ss` ter uma precisão só.
"""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Literal

from cronista.config import Settings
from cronista.domain.frames import frame_to_seconds
from cronista.pipeline.stage import StageError

Quality = Literal["preview", "delivery"]


def ffmpeg_cmd(
    settings: Settings, args: list[str], *, loglevel: str = "error", overwrite: bool = True
) -> list[str]:
    """Linha de comando completa do FFmpeg: `args` vem depois da base comum."""
    return [settings.ffmpeg, "-hide_banner", "-loglevel", loglevel, *(["-y"] if overwrite else []), *args]


def run_ffmpeg(settings: Settings, args: list[str], *, tail: int = 500) -> None:
    """Roda o FFmpeg até o fim; saída diferente de 0 vira `StageError` com o fim do `stderr`."""
    proc = subprocess.run(
        ffmpeg_cmd(settings, args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise StageError(f"ffmpeg falhou ({proc.returncode}): {proc.stderr.strip()[-tail:]}")


def run_ffmpeg_stderr(settings: Settings, args: list[str], *, what: str, tail: int = 300) -> str:
    """Roda o FFmpeg e devolve o `stderr` (onde filtros de medição, como o `ebur128`, escrevem)."""
    proc = subprocess.run(
        ffmpeg_cmd(settings, args, loglevel="info", overwrite=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise StageError(f"ffmpeg falhou ao {what}: {proc.stderr.strip()[-tail:]}")
    return proc.stderr


def pipe_raw(
    settings: Settings,
    args: list[str],
    *,
    chunk_bytes: int,
    unit_bytes: int = 1,
    between: Callable[[], None] | None = None,
    what: str = "ler quadros",
) -> Iterator[bytes]:
    """Saída bruta (`-f rawvideo -`) do FFmpeg em blocos de até `chunk_bytes`.

    `args` já termina em `-f rawvideo -`. O `stderr` vai para um arquivo: um pipe que ninguém drena enche
    (64 KB) e trava o FFmpeg com o stdout parado. Cada bloco devolvido é múltiplo de `unit_bytes` (um quadro
    inteiro); o resto parcial do fim é descartado. `between` roda antes de cada leitura (pausa por GPU
    ocupada).
    """
    cmd = ffmpeg_cmd(settings, args, overwrite=False)
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err)
        assert proc.stdout is not None
        try:
            while True:
                if between is not None:
                    between()
                data = proc.stdout.read(chunk_bytes)
                usable = len(data) // unit_bytes * unit_bytes
                if usable:
                    yield data[:usable]
                if len(data) < chunk_bytes:  # fim do fluxo (o pipe só devolve menos no EOF)
                    break
        finally:
            proc.stdout.close()
            code = proc.wait()
        if code != 0:
            err.seek(0)
            detail = err.read().decode(errors="replace").strip()[-500:]
            raise StageError(f"ffmpeg falhou ({code}) ao {what}: {detail}")


def grab_frame(
    settings: Settings,
    path: Path,
    frame: int,
    filters: str,
    out_args: list[str],
    *,
    timeout: float | None = 60,
) -> bytes | None:
    """Um quadro do vídeo (`frame` a 60 fps) passado por `filters`; `None` se o FFmpeg não entregou nada.

    `out_args`: formato de saída (`-f rawvideo -`, `-f image2pipe -c:v mjpeg -`...). Posiciona com `-ss` antes
    do `-i` (rápido; basta ao quadro porque o FFmpeg decodifica a partir do keyframe anterior).
    """
    args = [
        "-ss", f"{frame_to_seconds(frame):.6f}", "-i", str(path),
        "-frames:v", "1", "-vf", filters, *out_args,
    ]  # fmt: skip
    try:
        proc = subprocess.run(
            ffmpeg_cmd(settings, args, overwrite=False), capture_output=True, check=False, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 and proc.stdout else None


def video_args(settings: Settings, quality: Quality = "preview") -> list[str]:
    """Encoder de vídeo (`preview_encoder`: `libx264` em dev, `h264_nvenc` em prod).

    `preview`: rápido, para a prévia de revisão. `delivery`: o que vai para o Resolve ou para a publicação.
    """
    encoder = settings.preview_encoder
    if quality == "delivery":
        if encoder.endswith("_nvenc"):
            return ["-c:v", encoder, "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0"]
        return ["-c:v", encoder, "-preset", "medium", "-crf", "18"]
    if encoder.endswith("_nvenc"):
        return ["-c:v", encoder, "-preset", "p5", "-rc", "vbr", "-cq", str(settings.preview_crf), "-b:v", "0"]
    return ["-c:v", encoder, "-preset", "veryfast", "-crf", str(settings.preview_crf)]

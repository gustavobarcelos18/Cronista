"""Medição de loudness integrado (BS.1770 / EBU R128) e pico verdadeiro, pelo `ebur128` do FFmpeg."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from cronista.config import Settings
from cronista.pipeline.stage import StageError


@dataclass(frozen=True)
class Loudness:
    lufs: float | None
    """None quando o áudio é silêncio (nada acima do gate)."""
    true_peak_db: float | None


def parse_ebur128(stderr: str) -> Loudness:
    """Lê o resumo final do `ebur128` (`I:` em LUFS e `Peak:` em dBFS), ignorando as linhas de progresso."""
    summary = stderr[stderr.rfind("Summary:") :] if "Summary:" in stderr else stderr
    lufs = re.search(r"\bI:\s+(-?\d+(?:\.\d+)?|-inf)\s+LUFS", summary)
    peak = re.search(r"\bPeak:\s+(-?\d+(?:\.\d+)?|-inf)\s+dBFS", summary)

    def number(match: re.Match[str] | None) -> float | None:
        if match is None or match.group(1) == "-inf":
            return None
        return float(match.group(1))

    value = number(lufs)
    if value is not None and value <= -70.0:
        value = None
    return Loudness(value, number(peak))


def measure(settings: Settings, wav: Path) -> Loudness:
    cmd = [
        settings.ffmpeg,
        "-hide_banner",
        "-nostats",
        "-i",
        str(wav),
        "-af",
        "ebur128=peak=true",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    if proc.returncode != 0:
        raise StageError(f"ffmpeg falhou ao medir {wav.name}: {proc.stderr.strip()[-300:]}")
    return parse_ebur128(proc.stderr)

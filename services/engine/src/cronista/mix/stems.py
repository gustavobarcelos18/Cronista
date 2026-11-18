"""Stems A1/A2 (Fase 6B): um WAV por faixa cobrindo só os trechos usados, na ordem da timeline.

Decisão do histórico §53: o stem é a concatenação dos trechos da EDL (800 amostras por quadro a 48 kHz).
Trecho em timelapse fica em silêncio (o áudio do jogo é removido; a fala a
10x não serve). O áudio é escrito em blocos, nunca inteiro na memória.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import soundfile as sf

from cronista.assembly.plan import EditItem, Mode, Track
from cronista.domain.frames import FPS
from cronista.mix.envelope import FloatArray, gain_at
from cronista.pipeline.stage import StageError

RATE = 48_000
SAMPLES_PER_FRAME = RATE // FPS
BLOCK = RATE * 10


def render_stem(
    items: Sequence[EditItem],
    wavs: Mapping[int, Path],
    out: Path,
    curve: FloatArray | None = None,
) -> int:
    """Grava o stem em `out` (WAV float32 estéreo, 48 kHz) e devolve o total de amostras.

    `curve` é o ducking (ganho de controle); sem ele o stem sai cru (A6/A7).
    """
    v1 = [i for i in items if i.track == Track.V1]
    total = 0
    with sf.SoundFile(str(out), "w", samplerate=RATE, channels=2, subtype="FLOAT", format="WAV") as dest:
        for item in v1:
            want = item.timeline_frames * SAMPLES_PER_FRAME
            if item.mode == Mode.TIMELAPSE:
                _write_silence(dest, want)
            else:
                _copy_range(dest, wavs, item, want, curve, first_out=item.timeline_start * SAMPLES_PER_FRAME)
            total += want
    return total


def _write_silence(dest: sf.SoundFile, count: int) -> None:
    while count > 0:
        n = min(count, BLOCK)
        dest.write(np.zeros((n, 2), dtype=np.float32))
        count -= n


def _copy_range(
    dest: sf.SoundFile,
    wavs: Mapping[int, Path],
    item: EditItem,
    want: int,
    curve: FloatArray | None,
    first_out: int,
) -> None:
    path = wavs.get(item.file_id)
    if path is None:
        raise StageError(f"arquivo {item.file_id} sem WAV extraído (rode `cronista ingest` de novo)")
    with sf.SoundFile(str(path)) as src:
        if src.samplerate != RATE:
            raise StageError(
                f"{path.name}: {src.samplerate} Hz; o stem exige {RATE} Hz (a ingestão grava assim)"
            )
        src.seek(min(item.in_frame * SAMPLES_PER_FRAME, src.frames))
        done = 0
        while done < want:
            n = min(BLOCK, want - done)
            data = src.read(n, dtype="float32", always_2d=True)
            if data.shape[1] == 1:
                data = np.repeat(data, 2, axis=1)
            elif data.shape[1] > 2:
                data = data[:, :2]
            if len(data) < n:  # fim do arquivo antes do previsto: completa com silêncio
                data = np.concatenate([data, np.zeros((n - len(data), 2), dtype=np.float32)])
            if curve is not None:
                data = data * gain_at(curve, first_out + done, n, RATE)[:, None]
            dest.write(data.astype(np.float32))
            done += n

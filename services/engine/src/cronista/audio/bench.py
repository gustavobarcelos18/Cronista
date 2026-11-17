"""Benchmark de desempenho dos modelos de áudio (2B): velocidade, VRAM e RAM por modelo.

Mede **só desempenho**. A qualidade (WER, acerto dos eventos) é da 2C e precisa do gabarito.
Cada modelo roda primeiro num trecho curto (a primeira chamada baixa e carrega o modelo) e depois no
trecho de verdade, que é o que entra na medida. Os modelos rodam em sequência no mesmo processo, então
o teste também mostra se PyTorch e CTranslate2 convivem (a 1C testou as duas ordens, num ambiente à parte).
"""

from __future__ import annotations

import importlib
import json
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import soundfile as sf

from cronista.audio.ports import AudioModels
from cronista.gates import query_nvidia_smi

CLIP_BLOCK_S = 60.0  # o recorte é copiado em blocos deste tamanho, sem carregar tudo na memória


@dataclass
class BenchRow:
    model: str
    track: str
    audio_s: float
    wall_s: float
    warmup_s: float  # primeira chamada: inclui download e carga do modelo
    speed_x: float  # segundos de áudio por segundo de relógio (acima de 1 = mais rápido que o tempo real)
    vram_peak_mib: int | None  # pico (pesos + trabalho) acima do que a GPU usava antes de carregar o modelo
    ram_peak_mib: int | None  # RSS do processo (acumula os modelos já carregados antes)
    result_count: int
    note: str = ""

    @property
    def hours_per_10h(self) -> float:
        """Horas de relógio para analisar 10 h de gravação com este modelo."""
        return 10.0 / self.speed_x if self.speed_x else float("inf")


def gpu_used_mib() -> int | None:
    values = query_nvidia_smi("memory.used")
    return values[0] if values else None


def _rss_mib() -> int | None:
    try:
        psutil: Any = importlib.import_module("psutil")

        return int(psutil.Process().memory_info().rss / 2**20)
    except ImportError:
        return None


class _Peak:
    """Amostra a VRAM (nvidia-smi) e a RAM do processo a cada 0,5 s enquanto o modelo roda."""

    def __init__(self) -> None:
        self.gpu_base = gpu_used_mib()
        self.gpu_peak = self.gpu_base
        self.ram_peak = _rss_mib()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self) -> None:
        while not self._stop.wait(0.5):
            gpu, ram = gpu_used_mib(), _rss_mib()
            if gpu is not None:
                self.gpu_peak = max(self.gpu_peak or 0, gpu)
            if ram is not None:
                self.ram_peak = max(self.ram_peak or 0, ram)

    def __enter__(self) -> _Peak:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join()

    @property
    def vram_mib(self) -> int | None:
        if self.gpu_base is None or self.gpu_peak is None:
            return None
        return self.gpu_peak - self.gpu_base


def clip_wav(src: Path, dst: Path, start_s: float, seconds: float) -> float:
    """Recorta `[start_s, start_s + seconds)` do WAV sem carregá-lo todo. Devolve a duração gravada."""
    with sf.SoundFile(str(src)) as handle:
        rate, channels = handle.samplerate, handle.channels
        handle.seek(min(round(start_s * rate), handle.frames))
        remaining, written = round(seconds * rate), 0
        with sf.SoundFile(str(dst), "w", samplerate=rate, channels=channels, subtype="FLOAT") as out:
            while remaining > 0:
                block = min(remaining, round(CLIP_BLOCK_S * rate))
                data = handle.read(block, dtype="float32", always_2d=True)
                if len(data) == 0:
                    break
                out.write(data)
                remaining -= len(data)
                written += len(data)
    return float(written / rate)


def _measure(
    model: str, track: str, audio_s: float, warmup: Callable[[], Any], run: Callable[[], int], note: str = ""
) -> BenchRow:
    # VRAM: a linha de base é de antes da carga, então o pico inclui os pesos (o aquecimento os carrega).
    with _Peak() as peak:
        t0 = time.monotonic()
        warmup()
        warmup_s = time.monotonic() - t0
        t1 = time.monotonic()
        count = run()
        wall = time.monotonic() - t1
    return BenchRow(
        model=model,
        track=track,
        audio_s=round(audio_s, 1),
        wall_s=round(wall, 2),
        warmup_s=round(warmup_s, 1),
        speed_x=round(audio_s / wall, 1) if wall > 0 else 0.0,
        vram_peak_mib=peak.vram_mib,
        ram_peak_mib=peak.ram_peak,
        result_count=count,
        note=note,
    )


def run_bench(
    models: AudioModels, mic_wav: Path, game_wav: Path, work_dir: Path, minutes: float
) -> list[BenchRow]:
    """Mede VAD, transcrição e classificador (jogo e microfone) sobre os primeiros `minutes` de cada faixa."""
    work_dir.mkdir(parents=True, exist_ok=True)
    no_pause: Callable[[], None] = lambda: None  # noqa: E731
    mic = work_dir / "mic.clip.wav"
    game = work_dir / "game.clip.wav"
    mic_s = clip_wav(mic_wav, mic, 0.0, minutes * 60)
    game_s = clip_wav(game_wav, game, 0.0, minutes * 60)
    short = work_dir / "mic.warmup.wav"
    clip_wav(mic_wav, short, 0.0, 10.0)
    rows: list[BenchRow] = []

    spans: list[Any] = []
    if models.detector is not None:
        det = models.detector

        def run_vad() -> int:
            spans[:] = det.detect(mic, pause=no_pause)
            return len(spans)

        rows.append(_measure(det.name, "mic", mic_s, lambda: det.detect(short, pause=no_pause), run_vad))
    if models.transcriber is not None and spans:
        asr = models.transcriber
        speech_s = sum(s.end_s - s.start_s for s in spans)
        share = 100 * speech_s / mic_s if mic_s else 0.0
        rows.append(
            _measure(
                asr.name,
                "mic",
                mic_s,
                lambda: asr.transcribe(short, spans[:1], pause=no_pause),
                lambda: len(asr.transcribe(mic, spans, pause=no_pause)),
                note=f"só nos {speech_s:.0f} s de fala ({share:.0f}% do trecho)",
            )
        )
    elif models.transcriber is not None:
        why = "sem fala detectada no trecho" if models.detector is not None else "sem detector de fala (VAD)"
        rows.append(BenchRow("(transcrição)", "mic", mic_s, 0, 0, 0, None, None, 0, why))
    if models.classifier is not None:
        clf = models.classifier
        for track, clip, seconds in (("mic", mic, mic_s), ("game", game, game_s)):
            rows.append(
                _measure(
                    clf.name,
                    track,
                    seconds,
                    lambda: clf.classify(short, pause=no_pause),
                    lambda clip=clip: len(clf.classify(clip, pause=no_pause)),  # type: ignore[misc]
                    note="modelo já carregado na faixa anterior" if track == "game" else "",
                )
            )
    return rows


def render_table(rows: list[BenchRow]) -> str:
    cols = ("modelo", "faixa", "áudio", "relógio", "x tempo real", "10 h em", "VRAM MiB", "RAM MiB")
    head = (
        f"{cols[0]:<34}{cols[1]:<6}{cols[2]:>8}{cols[3]:>9}{cols[4]:>14}{cols[5]:>9}{cols[6]:>10}{cols[7]:>9}"
    )
    lines = [head, "-" * len(head)]
    for r in rows:
        lines.append(
            f"{r.model:<34}{r.track:<6}{r.audio_s:>7.0f}s{r.wall_s:>8.1f}s{r.speed_x:>14.1f}"
            f"{r.hours_per_10h:>8.2f}h{r.vram_peak_mib if r.vram_peak_mib is not None else '?':>10}"
            f"{r.ram_peak_mib if r.ram_peak_mib is not None else '?':>9}"
        )
        if r.note:
            lines.append(f"    {r.note}")
    return "\n".join(lines)


def write_results(rows: list[BenchRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(r) for r in rows], indent=2, ensure_ascii=False), encoding="utf-8")

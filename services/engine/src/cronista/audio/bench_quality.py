"""Benchmark de qualidade e desempenho dos modelos de áudio contra o gabarito (fala e eventos sonoros).

Cada candidato roda a etapa real (`SpeechStage` ou `SoundEventsStage`) nos WAVs da sessão e é avaliado com o
mesmo `quality.evaluate` do `bench-quality`; mede também tempo, VRAM e razão de tempo real. O JSON é regravado
a cada candidato, então interromper não perde o que já foi medido.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path
from typing import Any

from cronista.audio.adapters.audio_io import duration_s
from cronista.audio.bench import _Peak
from cronista.audio.events import events_from_result
from cronista.audio.ports import MIC_TRACK, SoundEventClassifier, SpeechDetector, Transcriber
from cronista.audio.quality import Utterance, evaluate
from cronista.audio.stages import SoundEventsStage, SpeechStage
from cronista.config import Settings
from cronista.domain.models import StageResult
from cronista.gabarito import Annotation
from cronista.pipeline import Stage, StageContext
from cronista.video.bench import free_gpu


@dataclass
class AudioQualityRow:
    candidate: str
    kind: str  # fala | eventos
    audio_s: float
    wall_s: float
    speed_x: float
    vram_peak_mib: int | None
    wer: float | None = None
    risada_precision: float | None = None
    risada_recall: float | None = None
    exclamacao_precision: float | None = None
    exclamacao_recall: float | None = None
    events: int = 0
    note: str = ""

    @property
    def hours_per_10h(self) -> float:
        return 10.0 / self.speed_x if self.speed_x else float("inf")


def _run_stage(stage: Stage, wavs: dict[str, Any], settings: Settings, out: Path) -> StageResult:
    out.mkdir(parents=True, exist_ok=True)
    ctx = StageContext(
        media_path=out, out_dir=out, settings=settings, inputs={"audio": StageResult(data=dict(wavs))}
    )
    return stage.run(ctx)


def _word_units(events: list[Any]) -> list[Utterance]:
    """Uma unidade por palavra, com o tempo dela: o WER não depende de como o modelo agrupa as frases.

    Sem isso, um modelo que junta várias frases anotadas num trecho só (o large-v3 faz isso) leva o texto
    inteiro como "inserção" em cada frase do gabarito. Sem palavras com tempo, cai para o trecho inteiro.
    """
    units: list[Utterance] = []
    for e in events:
        if e.kind != "fala":
            continue
        words = e.payload.get("words") or []
        if not words:
            units.append(Utterance(e.evidence.start_frame, e.evidence.end_frame, e.evidence.quote or ""))
            continue
        units.extend(Utterance(int(w["start_frame"]), int(w["end_frame"]), str(w["text"])) for w in words)
    return units


def _preload(stage: Stage) -> None:
    """Baixa e carrega o modelo antes da medida: o tempo mede a análise, não o download."""
    target = getattr(stage, "transcriber", None) or getattr(stage, "classifier", None)
    load = getattr(target, "_load", None)
    if callable(load):
        load()


def evaluate_events(
    result: StageResult, annotations: list[Annotation], tolerance_s: float
) -> tuple[dict[str, Any], int]:
    events = [e for e in (events_from_result(result) or [])]
    utterances = _word_units(events)
    marks = [(e.kind, (e.evidence.start_frame, e.evidence.end_frame)) for e in events if e.kind != "fala"]
    total = max([a.end_frame for a in annotations] + [iv[1] for _, iv in marks], default=0)
    report = evaluate(annotations, utterances, marks, [], total, tolerance_s)
    return {
        "wer": report.wer,
        "risada": report.detection["risada"],
        "exclamacao": report.detection["exclamacao"],
    }, len(events)


def _speech_stage(make: Callable[[], tuple[SpeechDetector, Transcriber]]) -> Stage:
    return SpeechStage(*make())


def _events_stage(make: Callable[[], SoundEventClassifier], min_score: float) -> Stage:
    return SoundEventsStage(make(), MIC_TRACK, min_score=min_score)


def run_quality_bench(
    settings: Settings,
    wavs: dict[str, Any],
    annotations: list[Annotation],
    speech: Mapping[str, Callable[[], tuple[SpeechDetector, Transcriber]]],
    events: Mapping[str, Callable[[], SoundEventClassifier]],
    work: Path,
    progress: Callable[[list[AudioQualityRow]], None] | None = None,
    tolerance_s: float = 1.0,
    min_score: float = 0.1,
) -> list[AudioQualityRow]:
    rows: list[AudioQualityRow] = []
    mic = Path(str(wavs[MIC_TRACK]))
    seconds = duration_s(mic)
    plan: list[tuple[str, str, Callable[[], Stage]]] = [
        *[(n, "fala", partial(_speech_stage, f)) for n, f in speech.items()],
        *[(n, "eventos", partial(_events_stage, f, min_score)) for n, f in events.items()],
    ]
    for name, kind, make in plan:
        try:
            stage = make()
            with _Peak() as peak:
                _preload(stage)
                t0 = time.monotonic()
                result = _run_stage(stage, wavs, settings, work / name)
                wall = time.monotonic() - t0
            metrics, count = evaluate_events(result, annotations, tolerance_s)
            row = AudioQualityRow(
                candidate=name,
                kind=kind,
                audio_s=round(seconds, 1),
                wall_s=round(wall, 1),
                speed_x=round(seconds / wall, 1) if wall > 0 else 0.0,
                vram_peak_mib=peak.vram_mib,
                wer=None if metrics["wer"] is None else round(metrics["wer"], 3),
                risada_precision=_r(metrics["risada"].precision),
                risada_recall=_r(metrics["risada"].recall),
                exclamacao_precision=_r(metrics["exclamacao"].precision),
                exclamacao_recall=_r(metrics["exclamacao"].recall),
                events=count,
            )
        except Exception as exc:  # modelo ausente, VRAM estourada, API diferente do esperado
            row = AudioQualityRow(name, kind, round(seconds, 1), 0.0, 0.0, None, note=f"falhou: {exc}"[:300])
        rows.append(row)
        free_gpu()
        if progress is not None:
            progress(rows)
    return rows


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def render_table(rows: list[AudioQualityRow]) -> str:
    head = (
        f"{'candidato':<24}{'tipo':<8}{'x t.real':>9}{'10 h em':>9}{'VRAM':>7}{'WER':>7}"
        f"{'risada P/R':>13}{'exclam. P/R':>13}{'eventos':>9}"
    )
    lines = [head, "-" * len(head)]

    def pr(p: float | None, r: float | None) -> str:
        return f"{_fmt(p)}/{_fmt(r)}"

    for r in rows:
        if r.speed_x == 0:
            lines.append(f"{r.candidate:<24}{r.kind:<8}{r.note}")
            continue
        wer = "-" if r.wer is None else f"{r.wer:.2f}"
        vram = r.vram_peak_mib if r.vram_peak_mib is not None else "?"
        lines.append(
            f"{r.candidate:<24}{r.kind:<8}{r.speed_x:>9.1f}{r.hours_per_10h:>8.2f}h{vram:>7}{wer:>7}"
            f"{pr(r.risada_precision, r.risada_recall):>13}"
            f"{pr(r.exclamacao_precision, r.exclamacao_recall):>13}{r.events:>9}"
        )
    return "\n".join(lines)


def to_json(rows: list[AudioQualityRow]) -> list[dict[str, Any]]:
    return [asdict(r) for r in rows]

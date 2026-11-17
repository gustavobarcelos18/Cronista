"""Etapas de análise de áudio. `audio_signals` roda em CPU sobre os WAVs extraídos pela ingestão."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cronista.audio import dsp
from cronista.audio.events import EVENTS_KEY, write_events_file
from cronista.audio.ports import (
    GAME_TRACK,
    MIC_EVENT_LABELS,
    MIC_TRACK,
    AudioModels,
    SoundEventClassifier,
    SpeechDetector,
    Transcriber,
)
from cronista.audio.signals import HOP_FRAMES, SIGNALS_KEY, SignalMeta, write_signal
from cronista.config import Settings
from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource, params_hash
from cronista.domain.frames import seconds_to_frame
from cronista.domain.models import StageResult
from cronista.pipeline.stage import Stage, StageContext, StageError, make_variant


class AudioSignalsStage:
    """Sinais numéricos por faixa: jogo (energia, novidade, periodicidade) e microfone (energia vs. sessão).

    Nunca lê a faixa 1 (mix): só os WAVs de jogo e microfone da etapa `audio`.
    """

    name = "audio_signals"
    version = "1"
    needs: tuple[str, ...] = ("audio",)
    uses_gpu = False

    def __init__(self, params: dsp.DspParams | None = None) -> None:
        self.dsp = params or dsp.DspParams(hop_frames=HOP_FRAMES)

    def params(self, settings: Settings) -> dict[str, Any]:
        return self.dsp.as_dict()

    def run(self, ctx: StageContext) -> StageResult:
        audio = ctx.inputs["audio"].data
        signals: dict[str, SignalMeta] = {}
        warnings: list[str] = []

        def emit(name: str, values: Any, unit: str, track: str) -> None:
            signals[name] = write_signal(
                ctx.out_dir,
                name,
                values,
                unit=unit,
                source_track=track,
                version=self.version,
                params=self.dsp.as_dict(),
                hop_frames=self.dsp.hop_frames,
            )

        game = _wav(audio, GAME_TRACK)
        base = dsp.analyze_track(game, self.dsp, with_onset=True, between_blocks=ctx.wait_for_gpu)
        emit("game.energy_db", base.energy_db, "dBFS", "game")
        emit("game.onset", base.onset, "dB", "game")
        emit("game.novelty", dsp.novelty(base.onset, self.dsp), "desvios", "game")
        emit("game.periodicity", dsp.periodicity(base.onset, self.dsp), "0-1", "game")

        mic = _wav(audio, MIC_TRACK)
        voice = dsp.analyze_track(mic, self.dsp, with_onset=False, between_blocks=ctx.wait_for_gpu)
        emit("mic.energy_db", voice.energy_db, "dBFS", "mic")
        emit("mic.energy_rel_db", dsp.energy_above_baseline(voice.energy_db, self.dsp), "dB", "mic")

        seconds = len(base.energy_db) * self.dsp.hop_s
        if seconds < self.dsp.baseline_s:
            warnings.append(
                f"Sessão de {seconds:.0f} s, menor que a linha de base ({self.dsp.baseline_s:.0f} s): "
                "novidade e energia relativa têm pouca referência"
            )
        return StageResult(
            files=[s.path for s in signals.values()],
            data={SIGNALS_KEY: {name: meta.model_dump() for name, meta in signals.items()}},
            warnings=warnings,
        )


def _checked(start_s: float, end_s: float, what: str) -> None:
    if end_s < start_s:
        raise StageError(f"{what} com intervalo invertido ({start_s:.2f}s..{end_s:.2f}s): erro do adaptador")


class SpeechStage:
    """VAD → transcrição só nos trechos de fala do microfone. Uma variante por par de modelos (benchmark)."""

    name = "speech"
    version = "1"
    needs: tuple[str, ...] = ("audio",)
    uses_gpu = True

    def __init__(self, detector: SpeechDetector, transcriber: Transcriber) -> None:
        self.detector, self.transcriber = detector, transcriber
        self.variant = make_variant(f"{detector.name}+{transcriber.name}")

    def params(self, settings: Settings) -> dict[str, Any]:
        return {
            "detector": [self.detector.name, self.detector.version, self.detector.options],
            "transcriber": [self.transcriber.name, self.transcriber.version, self.transcriber.options],
        }

    def run(self, ctx: StageContext) -> StageResult:
        wav = _wav(ctx.inputs["audio"].data, MIC_TRACK)
        spans = self.detector.detect(wav, pause=ctx.wait_for_gpu)
        for span in spans:
            _checked(span.start_s, span.end_s, "trecho de fala")
        utterances = [
            u for u in self.transcriber.transcribe(wav, spans, pause=ctx.wait_for_gpu) if u.text.strip()
        ]
        digest = params_hash(self.params(ctx.settings))

        events: list[AnalysisEvent] = []
        for u in utterances:
            _checked(u.start_s, u.end_s, "fala transcrita")
            start, end = seconds_to_frame(u.start_s), seconds_to_frame(u.end_s)
            events.append(
                AnalysisEvent(
                    kind="fala",
                    evidence=Evidence(
                        source=EvidenceSource.TRANSCRICAO,
                        start_frame=start,
                        end_frame=max(start, end),
                        confidence=u.confidence,
                        model=self.transcriber.name,
                        model_version=self.transcriber.version,
                        params_hash=digest,
                        quote=u.text.strip(),
                    ),
                    payload={
                        "words": [
                            {
                                "text": w.text,
                                "start_frame": seconds_to_frame(w.start_s),
                                "end_frame": seconds_to_frame(w.end_s),
                                "probability": w.probability,
                            }
                            for w in u.words
                        ],
                        "vad": [self.detector.name, self.detector.version],
                    },
                )
            )
        speech_json = ctx.out_dir / "speech.json"
        speech_json.write_text(
            json.dumps(
                {
                    "spans": [[seconds_to_frame(s.start_s), seconds_to_frame(s.end_s)] for s in spans],
                    "utterances": len(utterances),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        events_path = write_events_file(ctx.out_dir, events)
        warnings = [] if spans else ["Nenhuma fala detectada no microfone (faixa 3 muda ou muito baixa?)"]
        return StageResult(
            files=[str(speech_json), events_path],
            data={EVENTS_KEY: events_path, "speech": str(speech_json), "count": len(events)},
            warnings=warnings,
        )


class SoundEventsStage:
    """Eventos sonoros de uma faixa. No microfone só risada e grito (teclado e respiração são descartados)."""

    name = "sound_events"
    version = "1"
    needs: tuple[str, ...] = ("audio",)
    uses_gpu = True

    def __init__(self, classifier: SoundEventClassifier, track: str, min_score: float = 0.3) -> None:
        if track not in (GAME_TRACK, MIC_TRACK):
            raise ValueError(f"faixa desconhecida: {track}")
        self.classifier, self.track, self.min_score = classifier, track, min_score
        self.variant = make_variant(f"{track}-{classifier.name}")

    def params(self, settings: Settings) -> dict[str, Any]:
        return {
            "classifier": [self.classifier.name, self.classifier.version, self.classifier.options],
            "track": self.track,
            "min_score": self.min_score,
        }

    def run(self, ctx: StageContext) -> StageResult:
        wav = _wav(ctx.inputs["audio"].data, self.track)
        found = self.classifier.classify(wav, pause=ctx.wait_for_gpu)
        digest = params_hash(self.params(ctx.settings))
        events: list[AnalysisEvent] = []
        dropped = 0
        for span in found:
            _checked(span.start_s, span.end_s, f"evento '{span.label}'")
            if span.score < self.min_score or (
                self.track == MIC_TRACK and span.label not in MIC_EVENT_LABELS
            ):
                dropped += 1
                continue
            start, end = seconds_to_frame(span.start_s), seconds_to_frame(span.end_s)
            events.append(
                AnalysisEvent(
                    kind=span.label,
                    evidence=Evidence(
                        source=EvidenceSource.EVENTO,
                        start_frame=start,
                        end_frame=max(start, end),
                        confidence=span.score,
                        model=self.classifier.name,
                        model_version=self.classifier.version,
                        params_hash=digest,
                    ),
                    payload={"track": self.track},
                )
            )
        events_path = write_events_file(ctx.out_dir, events)
        return StageResult(
            files=[events_path],
            data={EVENTS_KEY: events_path, "count": len(events), "dropped": dropped},
        )


def analysis_stages(models: AudioModels) -> list[Stage]:
    """Etapas de análise de áudio para os modelos disponíveis, em ordem topológica.

    Os sinais de CPU rodam sempre; fala e eventos só com o modelo correspondente (`dev` não tem nenhum).
    """
    stages: list[Stage] = [AudioSignalsStage()]
    if models.detector is not None and models.transcriber is not None:
        stages.append(SpeechStage(models.detector, models.transcriber))
    if models.classifier is not None:
        stages.append(SoundEventsStage(models.classifier, GAME_TRACK))
        # Microfone: corte baixo porque risada curta dilui na janela de 10 s do AST (medido na 2C: 0,12).
        stages.append(SoundEventsStage(models.classifier, MIC_TRACK, min_score=0.1))
    return stages


def _wav(audio: dict[str, Any], label: str) -> Path:
    path = audio.get(label)
    if not path or not Path(str(path)).is_file():
        raise StageError(f"WAV da faixa '{label}' não encontrado: rode a ingestão (etapa audio)")
    return Path(str(path))

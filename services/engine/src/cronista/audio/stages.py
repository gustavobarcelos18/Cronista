"""Etapas de análise de áudio. `audio_signals` roda em CPU sobre os WAVs extraídos pela ingestão."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cronista.audio import dsp
from cronista.audio.signals import HOP_FRAMES, SIGNALS_KEY, SignalMeta, write_signal
from cronista.config import Settings
from cronista.domain.models import StageResult
from cronista.pipeline.stage import StageContext, StageError


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

        game = self._track(audio, "game")
        base = dsp.analyze_track(game, self.dsp, with_onset=True, between_blocks=ctx.wait_for_gpu)
        emit("game.energy_db", base.energy_db, "dBFS", "game")
        emit("game.onset", base.onset, "dB", "game")
        emit("game.novelty", dsp.novelty(base.onset, self.dsp), "desvios", "game")
        emit("game.periodicity", dsp.periodicity(base.onset, self.dsp), "0-1", "game")

        mic = self._track(audio, "mic")
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

    @staticmethod
    def _track(audio: dict[str, Any], label: str) -> Path:
        path = audio.get(label)
        if not path or not Path(str(path)).is_file():
            raise StageError(f"WAV da faixa '{label}' não encontrado: rode a ingestão (etapa audio)")
        return Path(str(path))

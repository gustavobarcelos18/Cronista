"""Etapas de análise de vídeo (Fase 3A): sinais visuais e eventos de tela, ambas em CPU sobre o proxy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from cronista.audio.events import EVENTS_KEY, write_events_file
from cronista.audio.signals import SIGNALS_KEY, SignalMeta, load_signal, signal_metas, write_signal
from cronista.config import Settings
from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource, params_hash
from cronista.domain.models import StageResult
from cronista.pipeline.stage import Stage, StageContext, StageError
from cronista.video import frames as vframes
from cronista.video.screen_state import ScreenParams, detect
from cronista.video.signals import SIGNAL_NAMES, FloatArray, SignalParams, block_signals

MODEL = "video-heuristica"


class VideoSignalsStage:
    """Sinais visuais do proxy (movimento, parada, luminância, bordas, deslocamento global, corte de cena)."""

    name = "video_signals"
    version = "1"
    needs: tuple[str, ...] = ("proxy",)
    uses_gpu = False

    def __init__(self, params: SignalParams | None = None) -> None:
        self.signal_params = params or SignalParams()

    def params(self, settings: Settings) -> dict[str, Any]:
        return {
            **self.signal_params.__dict__,
            "sample_fps": vframes.SAMPLE_FPS,
            "size": [vframes.WIDTH, vframes.HEIGHT],
        }

    def run(self, ctx: StageContext) -> StageResult:
        proxy = Path(str(ctx.inputs["proxy"].data.get("proxy", "")))
        if not proxy.is_file():
            raise StageError(f"proxy não encontrado: {proxy} (rode a ingestão de novo)")
        chunks: dict[str, list[FloatArray]] = {name: [] for name in SIGNAL_NAMES}
        previous = None
        # Sem GPU, mas todo processamento pausa com o OBS gravando ou jogo em tela cheia (CLAUDE.md).
        for frames in vframes.iter_gray_blocks(ctx.settings, proxy, between_blocks=ctx.wait_for_gpu):
            result = block_signals(frames, previous, self.signal_params)
            previous = (result.last_frame, result.last_hist)
            for name in SIGNAL_NAMES:
                chunks[name].append(result.values[name])
        if not chunks["motion"]:
            raise StageError("nenhum quadro lido do proxy (vídeo vazio ou sem trilha de vídeo)")
        signals: dict[str, SignalMeta] = {}
        for name in SIGNAL_NAMES:
            signals[f"video.{name}"] = write_signal(
                ctx.out_dir,
                f"video.{name}",
                np.concatenate(chunks[name]),
                unit="px" if name == "shift" else "0-1",
                source_track="video",
                version=self.version,
                params=self.params(ctx.settings),
                hop_frames=vframes.HOP_FRAMES,
                model=MODEL,
            )
        return StageResult(
            files=[s.path for s in signals.values()],
            data={SIGNALS_KEY: {name: meta.model_dump() for name, meta in signals.items()}},
        )


class VideoScenesStage:
    """Eventos de tela: cenas, menu, loading, idle e movimento de câmera, a partir dos sinais."""

    name = "video_scenes"
    version = "1"
    needs: tuple[str, ...] = ("video_signals",)
    uses_gpu = False

    def __init__(self, params: ScreenParams | None = None) -> None:
        self.screen = params or ScreenParams()

    def params(self, settings: Settings) -> dict[str, Any]:
        return dict(self.screen.__dict__)

    def run(self, ctx: StageContext) -> StageResult:
        metas = signal_metas(ctx.inputs["video_signals"])
        arrays: dict[str, FloatArray] = {
            name: np.asarray(load_signal(metas[f"video.{name}"]).values) for name in SIGNAL_NAMES
        }
        digest = params_hash(self.params(ctx.settings))
        hop = vframes.HOP_FRAMES
        events = [
            AnalysisEvent(
                kind=span.kind,
                evidence=Evidence(
                    source=EvidenceSource.CENA,
                    start_frame=span.start * hop,
                    end_frame=span.end * hop,
                    confidence=span.confidence,
                    model=MODEL,
                    model_version=self.version,
                    params_hash=digest,
                ),
                payload=dict(span.payload),
            )
            for span in detect(arrays, self.screen)
        ]
        path = write_events_file(ctx.out_dir, events)
        return StageResult(files=[path], data={EVENTS_KEY: path, "count": len(events)})


def video_stages() -> list[Stage]:
    """Etapas de análise de vídeo, em ordem topológica. Rodam em qualquer máquina (CPU, sem modelo)."""
    return [VideoSignalsStage(), VideoScenesStage()]

"""Timeline OTIO de uma sessão: V1 com um clipe por marcador, A1 = jogo, A2 = microfone.

60 fps exatos: todo tempo é um número inteiro de quadros (`RationalTime(frames, 60)`).
"""

from __future__ import annotations

import opentimelineio as otio
from opentimelineio.opentime import RationalTime, TimeRange

from cronista.domain.preview import ClipWindow
from cronista.montage import SessionPlan, SessionPlanError, SourceFile

FPS = 60


def _frames(seconds: float) -> int:
    return round(seconds * FPS)


def _range(start_frames: int, duration_frames: int) -> TimeRange:
    return TimeRange(RationalTime(start_frames, FPS), RationalTime(duration_frames, FPS))


def snap_window(window: ClipWindow, source: SourceFile) -> tuple[int, int]:
    """Início e duração em quadros inteiros, sem passar do fim do arquivo."""
    start = _frames(window.start_s)
    end = _frames(window.end_s)
    if source.duration_s is not None:
        end = min(end, int(source.duration_s * FPS))
    return start, max(0, end - start)


def _reference(path_uri: str, name: str, duration_frames: int) -> otio.schema.ExternalReference:
    reference = otio.schema.ExternalReference(target_url=path_uri, available_range=_range(0, duration_frames))
    reference.name = name
    return reference


def build_timeline(plan: SessionPlan, name: str) -> otio.schema.Timeline:
    """V1 (master), A1 (WAV do jogo) e A2 (WAV do microfone), os três com os mesmos trechos em sequência."""
    for source in plan.sources.values():
        if source.game_wav is None or source.mic_wav is None:
            raise SessionPlanError(
                f"{source.master.name}: WAVs de áudio não encontrados (rode `cronista ingest` de novo)"
            )

    timeline = otio.schema.Timeline(name=name, global_start_time=RationalTime(0, FPS))
    video = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    game = otio.schema.Track(name="A1", kind=otio.schema.TrackKind.Audio)
    mic = otio.schema.Track(name="A2", kind=otio.schema.TrackKind.Audio)

    for window in plan.windows:
        source = plan.sources[window.file_id]
        start, duration = snap_window(window, source)
        if duration == 0:
            continue
        total = _frames(source.duration_s) if source.duration_s is not None else start + duration
        label = f"{window.kind.value}|{window.marker_id}"
        for track, path in ((video, source.master), (game, source.game_wav), (mic, source.mic_wav)):
            assert path is not None
            track.append(
                otio.schema.Clip(
                    name=label,
                    media_reference=_reference(path.resolve().as_uri(), path.name, total),
                    source_range=_range(start, duration),
                )
            )
    timeline.tracks.extend([video, game, mic])
    return timeline

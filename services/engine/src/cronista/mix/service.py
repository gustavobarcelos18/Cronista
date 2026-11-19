"""Mixagem de uma sessão: plano de montagem + WAVs da ingestão + fala + roteiro → stems A1/A2/A6/A7."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from cronista.assembly.plan import EditPlan
from cronista.assembly.service import build_assembly
from cronista.audio.events import load_active_events
from cronista.config import Settings
from cronista.domain.frames import FPS
from cronista.media.ffmpeg import run_ffmpeg
from cronista.mix.envelope import (
    DuckParams,
    gain_curve,
    merge_intervals,
    narration_intervals,
    timeline_intervals,
)
from cronista.mix.loudness import Loudness, measure
from cronista.mix.stems import render_stem
from cronista.montage import SessionPlanError, load_source
from cronista.paths import SessionPaths, series_package_base
from cronista.pipeline.stage import StageError
from cronista.story.models import Script
from cronista.story.service import DEFAULT_TARGET_S, scope_sessions

VOICE_CHAIN = (
    "highpass=f=80,afftdn=nr=12:nf=-30,acompressor=threshold=0.125:ratio=3:attack=5:release=120:makeup=2"
)
LIMITER = "alimiter=limit=0.89:level=false"
"""Teto de pico em cerca de -1 dBFS; o -14 LUFS é do render final (plano 6.4)."""


@dataclass(frozen=True)
class MixParams:
    voice_lufs: float = -16.0
    game_lufs: float = -24.0
    """Leito do jogo: abaixo da voz, com folga para música e SFX da Fase 8."""
    duck: DuckParams = field(default_factory=DuckParams)


@dataclass
class StemReport:
    name: str
    path: str
    lufs: float | None
    true_peak_db: float | None
    gain_db: float = 0.0


@dataclass
class MixReport:
    directory: Path
    stems: list[StemReport] = field(default_factory=list)
    ducked_s: float = 0.0
    warnings: list[str] = field(default_factory=list)


def _final(settings: Settings, src: Path, dst: Path, filters: str) -> None:
    run_ffmpeg(settings, ["-i", str(src), "-af", filters, "-c:a", "pcm_s24le", str(dst)])


def _leveled(settings: Settings, src: Path, dst: Path, target_lufs: float, pre: str = "") -> StemReport:
    """Mede, aplica o ganho até o alvo e limita o pico; silêncio passa só pelo limitador."""
    base = src
    if pre:
        base = src.with_name(src.stem + ".pre.wav")
        _final(settings, src, base, pre)
    before = measure(settings, base)
    gain = 0.0 if before.lufs is None else target_lufs - before.lufs
    _final(settings, base, dst, f"volume={gain:.2f}dB,{LIMITER}")
    after = measure(settings, dst)
    if base != src:
        base.unlink(missing_ok=True)
    return StemReport(dst.name, str(dst), after.lufs, after.true_peak_db, round(gain, 2))


def mix_plan(
    plan: EditPlan,
    game_wavs: Mapping[int, Path],
    mic_wavs: Mapping[int, Path],
    speech_ranges: Mapping[int, Sequence[tuple[int, int]]],
    script: Script | None,
    settings: Settings,
    out_dir: Path,
    params: MixParams | None = None,
) -> MixReport:
    p = params or MixParams()
    out_dir.mkdir(parents=True, exist_ok=True)
    report = MixReport(out_dir)
    if not plan.v1:
        raise StageError("plano de montagem vazio; nada para mixar")

    voice = timeline_intervals(plan.items, speech_ranges)
    narration = narration_intervals(plan.items, script.lines if script else [])
    ducked = merge_intervals([*voice, *narration])
    report.ducked_s = sum(b - a for a, b in ducked) / FPS
    if not voice:
        report.warnings.append("sem fala ao vivo nos trechos: o ducking só segue o roteiro")
    curve = gain_curve(plan.total_frames, ducked, p.duck)

    tmp = out_dir / "_tmp"
    tmp.mkdir(exist_ok=True)
    try:
        game_raw, mic_raw = tmp / "game-raw.wav", tmp / "mic-raw.wav"
        game_duck = tmp / "game-duck.wav"
        render_stem(plan.items, game_wavs, game_raw)
        render_stem(plan.items, mic_wavs, mic_raw)
        render_stem(plan.items, game_wavs, game_duck, curve)

        report.stems.append(_leveled(settings, game_duck, out_dir / "A1-jogo.wav", p.game_lufs))
        report.stems.append(_leveled(settings, mic_raw, out_dir / "A2-voz.wav", p.voice_lufs, VOICE_CHAIN))
        for src, name in ((game_raw, "A6-jogo-cru.wav"), (mic_raw, "A7-microfone-cru.wav")):
            _final(settings, src, out_dir / name, "anull")
            m: Loudness = measure(settings, out_dir / name)
            report.stems.append(StemReport(name, str(out_dir / name), m.lufs, m.true_peak_db))
    finally:
        for leftover in tmp.glob("*"):
            leftover.unlink(missing_ok=True)
        tmp.rmdir()

    (out_dir / "mixagem.json").write_text(
        json.dumps(
            {
                "ducking_s": report.ducked_s,
                "avisos": report.warnings,
                "stems": [asdict(s) for s in report.stems],
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return report


def mix_session(
    db: Session,
    session_id: int | None,
    settings: Settings,
    script: Script | None = None,
    target_s: float = DEFAULT_TARGET_S,
    profile_objectives: tuple[list[str], list[str]] = ([], []),
    out_dir: Path | None = None,
    plan: EditPlan | None = None,
    project_id: int | None = None,
) -> MixReport:
    sessions = scope_sessions(db, session_id, project_id)
    plan = plan or build_assembly(db, session_id, settings, target_s, profile_objectives, None, project_id)
    game: dict[int, Path] = {}
    mic: dict[int, Path] = {}
    speech: dict[int, list[tuple[int, int]]] = {}
    for media in (m for s in sessions for m in sorted(s.media_files, key=lambda m: m.ordinal)):
        source = load_source(db, media)
        if source.game_wav is None or source.mic_wav is None:
            raise SessionPlanError(
                f"{source.master.name}: WAVs não encontrados (rode `cronista ingest` de novo)"
            )
        game[media.id], mic[media.id] = source.game_wav, source.mic_wav
        speech[media.id] = [
            (e.evidence.start_frame, e.evidence.end_frame)
            for e in load_active_events(db, media.id)
            if e.kind == "fala"
        ]
    if out_dir is not None:
        target = out_dir
    elif project_id is not None:
        target = series_package_base(settings, project_id) / "stems"
    else:
        target = SessionPaths.of(settings, session_id or 0).stems_dir
    return mix_plan(plan, game, mic, speech, script, settings, target)

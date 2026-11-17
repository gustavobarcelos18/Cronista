"""Mixagem de uma sessão: plano de montagem + WAVs da ingestão + fala + roteiro → stems A1/A2/A6/A7."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from cronista.assembly.plan import EditPlan
from cronista.assembly.service import build_assembly
from cronista.audio.events import load_active_events
from cronista.config import Settings
from cronista.db.models import RecordingSession
from cronista.domain.frames import FPS
from cronista.mix.envelope import (
    DuckParams,
    gain_curve,
    merge_intervals,
    narration_intervals,
    timeline_intervals,
)
from cronista.mix.loudness import Loudness, measure
from cronista.mix.stems import render_stem
from cronista.montage import SessionPlanError, _load_source
from cronista.pipeline.stage import StageError
from cronista.story.models import Script

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


def _ffmpeg(settings: Settings, args: list[str]) -> None:
    proc = subprocess.run(
        [settings.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise StageError(f"ffmpeg falhou ({proc.returncode}): {proc.stderr.strip()[-400:]}")


def _final(settings: Settings, src: Path, dst: Path, filters: str) -> None:
    _ffmpeg(settings, ["-i", str(src), "-af", filters, "-c:a", "pcm_s24le", str(dst)])


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
    session_id: int,
    settings: Settings,
    script: Script | None = None,
    target_s: float = 40 * 60.0,
    profile_objectives: tuple[list[str], list[str]] = ([], []),
    out_dir: Path | None = None,
    plan: EditPlan | None = None,
) -> MixReport:
    plan = plan or build_assembly(db, session_id, settings, target_s, profile_objectives)
    session = db.get(RecordingSession, session_id)
    assert session is not None
    game: dict[int, Path] = {}
    mic: dict[int, Path] = {}
    speech: dict[int, list[tuple[int, int]]] = {}
    for media in session.media_files:
        source = _load_source(db, media)
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
    target = out_dir or settings.data_dir / "export" / "stems" / str(session_id)
    return mix_plan(plan, game, mic, speech, script, settings, target)

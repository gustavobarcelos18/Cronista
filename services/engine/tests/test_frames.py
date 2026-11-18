"""T1: tempo em quadros num único lugar (`domain/frames`)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cronista.config import Settings
from cronista.domain.frames import FPS, duration_frames, fcpxml_time, frame_to_seconds, seconds_to_frame


@pytest.mark.parametrize("t", [0.0, 0.0083, 1 / 60, 12.3456, 3600.0, 36_000.016])
def test_round_trip_is_within_half_a_frame(t: float) -> None:
    assert abs(frame_to_seconds(seconds_to_frame(t)) - t) <= 0.5 / FPS + 1e-9


@pytest.mark.parametrize("t", [0.0, 0.0166, 1 / 60, 10.0, 59.999, 7200.123456, 36_000.016])
def test_duration_never_passes_the_real_end(t: float) -> None:
    assert duration_frames(t) <= t * FPS + 1e-9
    assert duration_frames(t) > t * FPS - 1


def test_fcpxml_time_is_an_integer_number_of_frames() -> None:
    assert fcpxml_time(90) == "90/60s" and fcpxml_time(89.6) == "90/60s"


def test_expected_fps_cannot_diverge_from_the_constant() -> None:
    assert Settings(env="t", data_dir="x").expected_fps == "60/1"
    with pytest.raises(ValidationError):
        Settings(env="t", data_dir="x", expected_fps="30/1")


def test_there_is_a_single_fps_definition() -> None:
    import pathlib
    import re

    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "cronista"
    defs = [
        p.relative_to(src).as_posix()
        for p in src.rglob("*.py")
        if re.search(r"^FPS\s*=\s*\d+", p.read_text(encoding="utf-8"), re.M)
    ]
    # devtools/ gera mídia de teste fora do produto; db/migrations fixa os valores de cada migração
    assert [d for d in defs if not d.startswith(("devtools", "db"))] == ["domain/frames.py"]

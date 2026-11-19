from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from cronista.config import find_repo_root
from cronista.profiles import (
    GENERIC,
    GameProfile,
    apply_thresholds,
    load_profile,
    render_profile_schema,
    resolve_profile,
)
from cronista.video.hud import IdleParams
from cronista.video.screen_state import ScreenParams

ROOT = find_repo_root(Path(__file__))
PROFILES = ROOT / "profiles"
SRC = Path(__file__).resolve().parents[1] / "src" / "cronista"


def test_generic_profile_adds_nothing() -> None:
    assert GENERIC.hud_regions == [] and GENERIC.thresholds == {} and GENERIC.camera_tools == []
    assert apply_thresholds(GENERIC, "screen", ScreenParams()) == ScreenParams()


def test_example_profile_loads_and_adjusts_thresholds() -> None:
    profile = load_profile(PROFILES / "exemplo.yaml")
    assert profile.hud_regions[0].tag_theme
    assert next(t.name for t in profile.camera_tools) == "Replay Mod"
    adjusted = apply_thresholds(profile, "idle", IdleParams())
    assert adjusted.min_seconds == 10.0 and IdleParams().min_seconds == 10.0


def test_threshold_override_returns_copy() -> None:
    profile = GameProfile(name="x", thresholds={"screen": {"menu_edge": 0.2}})
    out = apply_thresholds(profile, "screen", ScreenParams())
    assert out.menu_edge == 0.2 and ScreenParams().menu_edge == 0.12


@pytest.mark.parametrize(
    "data",
    [
        {"name": "x", "thresholds": {"nada": {"a": 1}}},
        {"name": "x", "thresholds": {"screen": {"inexistente": 1}}},
        {"name": "X Maiúsculo"},
        {"name": "x", "hud_regions": [{"name": "a", "x": 0.9, "y": 0, "w": 0.3, "h": 0.1}]},
        {
            "name": "x",
            "hud_regions": [
                {"name": "a", "x": 0, "y": 0, "w": 0.1, "h": 0.1},
                {"name": "a", "x": 0.5, "y": 0, "w": 0.1, "h": 0.1},
            ],
        },
        {"name": "x", "campo_extra": 1},
    ],
)
def test_invalid_profiles_are_rejected(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GameProfile.model_validate(data)


def test_resolve_profile(tmp_path: Path) -> None:
    assert resolve_profile("", tmp_path) is GENERIC
    assert resolve_profile("generico", tmp_path) is GENERIC
    assert resolve_profile("exemplo", PROFILES).name == "exemplo"
    with pytest.raises(FileNotFoundError):
        resolve_profile("nao-existe", tmp_path)
    with pytest.raises(ValueError):
        resolve_profile("../fora", tmp_path)


def test_versioned_profile_schema_is_up_to_date() -> None:
    """Se falhar: `uv run python -m cronista.profiles`."""
    assert (PROFILES / "profile.schema.json").read_text(encoding="utf-8") == render_profile_schema()


def test_core_never_imports_or_names_a_profile() -> None:
    """Plugabilidade: acrescentar um perfil não toca o núcleo. Só `profiles.py` (e a CLI) conhecem perfis."""
    allowed = {
        "profiles.py",
        "cli.py",
        "common.py",
        "narrative.py",
        "devtools.py",
        "capture.py",
        "assembly.py",
        "packaging.py",
    }
    import_re = re.compile(
        r"^\s*(from|import)\s+cronista\.profiles\b|^\s*from\s+cronista\s+import\s+.*\bprofiles\b", re.M
    )
    names = {p.stem for p in PROFILES.glob("*.yaml")}
    game_re = re.compile(r"minecraft|\bgta\b|zelda|terraria|stardew", re.I)
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if path.name not in allowed and import_re.search(text):
            offenders.append(f"{path.relative_to(SRC)}: importa perfis")
        if path.name != "profiles.py" and (game_re.search(text) or any(f'"{n}"' in text for n in names)):
            offenders.append(f"{path.relative_to(SRC)}: cita jogo ou perfil")
    assert offenders == []

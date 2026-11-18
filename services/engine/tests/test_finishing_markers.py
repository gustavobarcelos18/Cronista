"""Marcadores das sugestões (8D). Só biblioteca padrão, como o plano."""

from __future__ import annotations

from cronista.finishing.effects import EffectKind, EffectMode
from cronista.finishing.markers import SUGGESTION_COLORS, SUGGESTION_NAMES, describe, suggestion_markers
from cronista.finishing.plan import FinishItem, FinishPlan, Track

CREATOR_COLORS = {"Red", "Yellow", "Green", "Purple", "Cyan", "Pink", "Fuchsia", "Blue"}


def item(kind: EffectKind, mode: EffectMode, start: int, **extra: object) -> FinishItem:
    values: dict[str, object] = {
        "id": f"{kind.value}-{start}",
        "kind": kind,
        "mode": mode,
        "track": Track.V2,
        "start": start,
        "frames": 90,
        "intensity": 0.75,
        "chapter": 1,
        "moment_id": "m1",
        "asset_id": None,
        "params": {"escala": 1.2},
        "reason": "nota 0.90 em conflito",
    }
    values.update(extra)
    return FinishItem(**values)  # type: ignore[arg-type]


def test_only_suggestions_become_markers_in_frame_order() -> None:
    plan = FinishPlan(
        items=[
            item(EffectKind.ZOOM, EffectMode.EDITAVEL, 10),
            item(EffectKind.SHAKE, EffectMode.SUGERIR, 600),
            item(EffectKind.SFX, EffectMode.SUGERIR, 120, frames=0, asset_id="som-morte"),
            item(EffectKind.ZOOM, EffectMode.RENDERIZADO, 30),
        ]
    )
    marks = suggestion_markers(plan)
    assert [m.frame for m in marks] == [120, 600]
    assert marks[0].custom == "acabamento|sfx-120" and marks[0].name == "Sugestão: efeito sonoro"
    assert "item som-morte" in marks[0].note and "intensidade 0.75" in marks[0].note


def test_no_suggestions_no_markers() -> None:
    assert suggestion_markers(FinishPlan(items=[item(EffectKind.ZOOM, EffectMode.EDITAVEL, 0)])) == []


def test_note_has_duration_only_when_known() -> None:
    assert "1.5 s" in describe(item(EffectKind.ZOOM, EffectMode.SUGERIR, 0))
    assert " s;" not in describe(item(EffectKind.SFX, EffectMode.SUGERIR, 0, frames=0)).replace("nota", "")


def test_suggestion_colors_do_not_clash_with_creator_markers() -> None:
    assert not set(SUGGESTION_COLORS.values()) & CREATOR_COLORS
    assert set(SUGGESTION_COLORS) <= set(SUGGESTION_NAMES)

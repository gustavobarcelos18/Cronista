from __future__ import annotations

from cronista.assembly.plan import Card, EditItem, EditPlan, Mode, Track
from cronista.domain.frames import FPS
from cronista.domain.frames import FPS as DOMAIN_FPS
from cronista.finishing.brand import BrandKit, resolve_style
from cronista.finishing.effects import EffectKind
from cronista.finishing.library import Library, LibraryItem
from cronista.finishing.service import assets_from_library, finish_from_edit_plan, moments_from_plan

VISUAL = {
    "palette": {
        "primary": "#112233",
        "secondary": "#223344",
        "accent": "#334455",
        "background": "#000000",
        "text": "#FFFFFF",
    },
    "fonts": {"title": "A", "body": "B"},
}


def edit_item(
    segment_id: str, start: int, *, mode: Mode = Mode.AO_VIVO, track: Track = Track.V1, score: float = 0.9
) -> EditItem:
    return EditItem(
        file_id=1,
        in_frame=0,
        out_frame=600,
        track=track,
        mode=mode,
        speed=1 if mode != Mode.TIMELAPSE else 10,
        reason="teste",
        chapter=1,
        beat="falha",
        segment_id=segment_id,
        score=score,
        timeline_start=start,
    )


def test_fps_is_the_domain_fps() -> None:
    assert FPS == DOMAIN_FPS


def test_moments_only_from_v1_with_markers_and_live_flag() -> None:
    plan = EditPlan(
        items=[
            edit_item("a-1", 0),
            edit_item("a-2", 600, mode=Mode.TIMELAPSE, score=1.7),
            edit_item("b-1", 0, mode=Mode.BROLL, track=Track.V3),
        ]
    )
    moments = moments_from_plan(plan, {"a-1": frozenset({"morte_falha"})})
    assert [m.start for m in moments] == [0, 600]
    assert moments[0].tags == frozenset({"morte_falha"}) and moments[0].live
    assert not moments[1].live and moments[1].score == 1.0  # nota limitada a 1


def test_assets_skip_non_commercial_by_default() -> None:
    base = {"file": "x.wav", "kind": "sfx", "origin": "propria", "license": "propria"}
    lib = Library(
        items=[
            LibraryItem.model_validate({**base, "id": "livre"}),
            LibraryItem.model_validate({**base, "id": "restrito", "commercial_use": False}),
        ]
    )
    assert [a.id for a in assets_from_library(lib)] == ["livre"]
    assert [a.id for a in assets_from_library(lib, commercial=False)] == ["livre", "restrito"]


def test_finish_from_edit_plan_uses_style_budget_and_cards() -> None:
    plan = EditPlan(items=[edit_item("a-1", 0), edit_item("a-2", 600)], cards=[Card(1, 0, 180, "Capítulo 1")])
    style = resolve_style(BrandKit.model_validate({"name": "t", "visual": VISUAL}))
    finish = finish_from_edit_plan(plan, {"a-1": frozenset({"morte_falha"})}, style)
    assert [i.start for i in finish.of(EffectKind.CARTELA_DIA)] == [0]
    again = finish_from_edit_plan(plan, {"a-1": frozenset({"morte_falha"})}, style)
    assert finish.input_hash == again.input_hash
    assert all(i.start >= 0 and i.end <= plan.total_frames for i in finish.items)

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from cronista.assembly.plan import EditItem, EditPlan, Mode, Track
from cronista.domain.frames import FPS
from cronista.export.finish_fcpxml import AudioFile, FinishLayers
from cronista.export.montagem import ExportMedia, MediaFileInfo, check_plan_fcpxml, render_plan_fcpxml
from cronista.finishing.effects import EffectKind, EffectMode
from cronista.finishing.plan import FinishItem, FinishPlan
from cronista.finishing.plan import Track as FxTrack


def cut(start: int, *, in_frame: int, frames: int, mode: Mode = Mode.AO_VIVO, speed: int = 1) -> EditItem:
    return EditItem(
        file_id=1,
        in_frame=in_frame,
        out_frame=in_frame + frames * speed,
        track=Track.V1,
        mode=mode,
        speed=speed,
        reason="t",
        chapter=1,
        beat="falha",
        segment_id=f"s{start}",
        score=0.9,
        timeline_start=start,
    )


def fx(
    kind: EffectKind,
    start: int,
    frames: int,
    mode: EffectMode,
    item_id: str,
    *,
    asset: str | None = None,
    params: dict[str, float | int | str] | None = None,
) -> FinishItem:
    track = {
        EffectKind.ZOOM: FxTrack.V2,
        EffectKind.SHAKE: FxTrack.V2,
        EffectKind.CONTADOR_MORTES: FxTrack.V4,
        EffectKind.MUSICA: FxTrack.A4,
    }.get(kind, FxTrack.A5)
    return FinishItem(item_id, kind, mode, track, start, frames, 0.8, 1, "m", asset, params or {}, "t")


def setup(tmp_path: Path, items: list[FinishItem]) -> tuple[EditPlan, ExportMedia, FinishLayers]:
    def touch(name: str) -> Path:
        path = tmp_path / name
        path.write_bytes(b"x")
        return path

    plan = EditPlan(items=[cut(0, in_frame=100, frames=600), cut(600, in_frame=5000, frames=600)])
    media = ExportMedia(
        {1: MediaFileInfo(touch("master.mp4"), 20000)},
        {},
        {k: touch(f"{k}.wav") for k in ("A1", "A2", "A4", "A6", "A7")},
        plan.total_frames,
    )
    layers = FinishLayers(
        FinishPlan(items=items),
        rendered={"z-render": touch("zoom.mp4"), "c-render": touch("contador.mov")},
        rendered_frames={"z-render": 90, "c-render": 180},
        audio={"boom": AudioFile(touch("boom.wav"), 30), "tema": AudioFile(touch("tema.wav"), 3000)},
        texts={"c-edit": "Mortes: 4"},
    )
    return plan, media, layers


def clips_by_name(xml: str) -> dict[str, ET.Element]:
    return {c.get("name", ""): c for c in ET.fromstring(xml).iter("asset-clip")}


def test_rendered_zoom_goes_to_lane_1_inside_the_right_cut(tmp_path: Path) -> None:
    plan, media, layers = setup(tmp_path, [fx(EffectKind.ZOOM, 650, 90, EffectMode.RENDERIZADO, "z-render")])
    xml = render_plan_fcpxml(plan, media, "t", layers)
    clip = clips_by_name(xml)["zoom|z-render"]
    assert clip.get("lane") == "1" and clip.get("start") == "0s" and clip.get("duration") == "90/60s"
    assert clip.get("offset") == f"{5000 + 50}/{FPS}s"  # tempo do pai (cortes 2) = quadro de origem + 50
    assert check_plan_fcpxml(xml, plan) == []


def test_editable_zoom_is_a_copy_of_the_cut_with_closed_keyframes(tmp_path: Path) -> None:
    plan, media, layers = setup(
        tmp_path, [fx(EffectKind.ZOOM, 30, 90, EffectMode.EDITAVEL, "z-edit", params={"escala": 1.2})]
    )
    xml = render_plan_fcpxml(plan, media, "t", layers)
    clip = clips_by_name(xml)["zoom|z-edit"]
    parent_ref = next(
        c for c in ET.fromstring(xml).iter("asset-clip") if c.get("name", "").startswith("ao_vivo|s0")
    )
    assert clip.get("ref") == parent_ref.get("ref") and clip.get("start") == "130/60s"
    keys = list(clip.iter("keyframe"))
    assert keys[0].get("value") == "1.00000 1.00000" and keys[-1].get("value") == "1.00000 1.00000"
    assert any(abs(float(k.get("value", "1").split()[0]) - 1.2) < 0.01 for k in keys)  # o pico
    assert keys[-1].get("time") == f"{130 + 89}/{FPS}s"


def test_editable_shake_has_scale_and_position_keyframes_every_frame(tmp_path: Path) -> None:
    plan, media, layers = setup(
        tmp_path, [fx(EffectKind.SHAKE, 10, 36, EffectMode.EDITAVEL, "s", params={"amplitude_px": 10})]
    )
    root = ET.fromstring(render_plan_fcpxml(plan, media, "t", layers))
    clip = clips_by_name(ET.tostring(root, encoding="unicode"))["shake|s"]
    params = {p.get("name"): list(p.iter("keyframe")) for p in clip.iter("param")}
    assert len(params["scale"]) == len(params["position"]) == 36
    assert params["scale"][0].get("value") == "1.00000 1.00000"  # começa no enquadramento original
    assert all(abs(float(v)) < 1 for k in params["position"] for v in k.get("value", "0 0").split())


def test_effects_never_land_on_timelapse_and_sugerir_is_ignored(tmp_path: Path) -> None:
    plan, media, layers = setup(
        tmp_path,
        [
            fx(EffectKind.ZOOM, 30, 90, EffectMode.SUGERIR, "z-sug"),
            fx(EffectKind.ZOOM, 30, 90, EffectMode.EDITAVEL, "z-edit"),
        ],
    )
    plan.items[0] = cut(0, in_frame=100, frames=600, mode=Mode.TIMELAPSE, speed=10)
    media.timelapses = {0: tmp_path / "tl.mp4"}
    (tmp_path / "tl.mp4").write_bytes(b"x")
    names = clips_by_name(render_plan_fcpxml(plan, media, "t", layers))
    assert not any(n.startswith("zoom|") for n in names)


def test_counter_rendered_overlay_and_editable_title(tmp_path: Path) -> None:
    plan, media, layers = setup(
        tmp_path,
        [
            fx(EffectKind.CONTADOR_MORTES, 100, 180, EffectMode.RENDERIZADO, "c-render", params={"ordem": 3}),
            fx(EffectKind.CONTADOR_MORTES, 700, 180, EffectMode.EDITAVEL, "c-edit", params={"ordem": 4}),
        ],
    )
    xml = render_plan_fcpxml(plan, media, "t", layers)
    overlay = clips_by_name(xml)["contador|c-render"]
    assert overlay.get("lane") == "3" and overlay.get("duration") == "180/60s"
    titles = [t for t in ET.fromstring(xml).iter("title") if t.get("name") == "contador|c-edit"]
    assert len(titles) == 1 and titles[0].get("lane") == "3"
    assert titles[0].findtext("text/text-style") == "Mortes: 4"
    assert check_plan_fcpxml(xml, plan) == []


def test_sfx_lane_gain_and_trim_at_cut_end(tmp_path: Path) -> None:
    plan, media, layers = setup(
        tmp_path,
        [
            fx(EffectKind.SFX, 100, 0, EffectMode.EDITAVEL, "sfx-1", asset="boom", params={"ganho_db": -6.5}),
            fx(EffectKind.SFX, 590, 0, EffectMode.EDITAVEL, "sfx-2", asset="boom"),
        ],
    )
    sfx = [
        c
        for c in ET.fromstring(render_plan_fcpxml(plan, media, "t", layers)).iter("asset-clip")
        if c.get("lane") == "-5"
    ]
    assert [c.get("duration") for c in sfx] == ["30/60s", "10/60s"]  # o segundo é aparado no fim do corte
    gain = sfx[0].find("adjust-volume")
    assert gain is not None and gain.get("amount") == "-6.5dB"


def test_editable_music_is_split_across_cuts_and_keeps_file_offsets(tmp_path: Path) -> None:
    plan, media, layers = setup(
        tmp_path, [fx(EffectKind.MUSICA, 500, 400, EffectMode.EDITAVEL, "musica-1", asset="tema")]
    )
    xml = render_plan_fcpxml(plan, media, "t", layers)
    parts = [c for c in ET.fromstring(xml).iter("asset-clip") if c.get("name") == "musica|tema"]
    assert [(p.get("lane"), p.get("start"), p.get("duration")) for p in parts] == [
        ("-4", "0/60s", "100/60s"),
        ("-4", "100/60s", "300/60s"),
    ]
    assert parts[0].get("offset") == f"{100 + 500}/{FPS}s"  # fim do corte 1 (tempo do pai: origem 100 + 500)
    assert parts[1].get("offset") == f"{5000}/{FPS}s"


def test_rendered_music_uses_the_a4_stem_lane(tmp_path: Path) -> None:
    plan, media, layers = setup(
        tmp_path, [fx(EffectKind.MUSICA, 0, 600, EffectMode.RENDERIZADO, "m", asset="tema")]
    )
    xml = render_plan_fcpxml(plan, media, "t", layers)
    stems = [c for c in ET.fromstring(xml).iter("asset-clip") if c.get("name") == "A4"]
    assert len(stems) == 2 and all(c.get("lane") == "-4" for c in stems)
    assert not [c for c in ET.fromstring(xml).iter("asset-clip") if c.get("name") == "musica|tema"]


def test_without_layers_the_output_is_unchanged(tmp_path: Path) -> None:
    plan, media, _ = setup(tmp_path, [fx(EffectKind.ZOOM, 30, 90, EffectMode.EDITAVEL, "z")])
    media.stems = {k: v for k, v in media.stems.items() if k != "A4"}
    assert render_plan_fcpxml(plan, media, "t") == render_plan_fcpxml(plan, media, "t", None)
    lanes = {c.get("lane") for c in ET.fromstring(render_plan_fcpxml(plan, media, "t")).iter("asset-clip")}
    assert "1" not in lanes and "-5" not in lanes

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
import soundfile

from cronista.assembly.plan import EditItem, EditPlan, Mode, Track
from cronista.config import Settings
from cronista.export.finish_fcpxml import FinishLayers
from cronista.export.montagem import ExportMedia, MediaFileInfo, check_plan_fcpxml, render_plan_fcpxml
from cronista.finishing.apply import FinishArtifacts, apply_finishing, leia_me_section, lua_lut
from cronista.finishing.brand import BrandKit, resolve_style
from cronista.finishing.effects import EffectKind, EffectMode
from cronista.finishing.library import Library, LibraryItem
from cronista.finishing.plan import FinishItem, FinishPlan, apply_decisions
from cronista.finishing.plan import Track as FxTrack

BRAND = BrandKit.model_validate(
    {
        "name": "t",
        "visual": {
            "palette": {
                "primary": "#112233",
                "secondary": "#223344",
                "accent": "#334455",
                "background": "#101010",
                "text": "#FF8000",
            },
            "fonts": {"title": "Titulo", "body": "B", "files": ["fonts/T.ttf"]},
            "lut": "luts/serie.cube",
        },
    }
)


def cut(start: int, in_frame: int, frames: int = 600) -> EditItem:
    return EditItem(
        file_id=1,
        in_frame=in_frame,
        out_frame=in_frame + frames,
        track=Track.V1,
        mode=Mode.AO_VIVO,
        speed=1,
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
    asset: str | None = None,
    params: dict[str, float | int | str] | None = None,
) -> FinishItem:
    track = {
        EffectKind.ZOOM: FxTrack.V2,
        EffectKind.CONTADOR_MORTES: FxTrack.V4,
        EffectKind.MUSICA: FxTrack.A4,
        EffectKind.COR_LUT: FxTrack.V1,
    }.get(kind, FxTrack.A5)
    return FinishItem(item_id, kind, mode, track, start, frames, 0.8, 1, "m", asset, params or {}, "motivo")


@dataclass
class Env:
    tmp: Path
    calls: list[tuple[str, list[str]]]
    library: Library
    brand_dir: Path
    directory: Path
    settings: Settings


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    calls: list[tuple[str, list[str]]] = []

    def recorder(label: str) -> Callable[[Settings, list[str]], None]:
        def run(_s: Settings, args: list[str]) -> None:
            calls.append((label, args))
            Path(args[-1]).write_bytes(b"x")

        return run

    for module, label in (("video", "v"), ("overlay", "o"), ("audio", "a")):
        monkeypatch.setattr(f"cronista.finishing.render.{module}.run_ffmpeg", recorder(label))

    library_dir = tmp_path / "lib"
    library_dir.mkdir()
    soundfile.write(str(library_dir / "boom.wav"), np.zeros(48000, dtype="float32"), 48000)  # 60 quadros
    soundfile.write(str(library_dir / "tema.wav"), np.zeros(48000 * 5, dtype="float32"), 48000)  # 300 quadros
    library = Library(
        items=[
            LibraryItem(
                id="boom", file="boom.wav", kind="sfx", tags=["morte"], origin="propria", license="propria"
            ),
            LibraryItem(
                id="tema", file="tema.wav", kind="musica", origin="propria", license="propria", bpm=120
            ),
        ]
    )
    brand_dir = tmp_path / "brand"
    (brand_dir / "luts").mkdir(parents=True)
    (brand_dir / "luts" / "serie.cube").write_text("LUT_3D_SIZE 2", encoding="utf-8")
    (brand_dir / "fonts").mkdir()
    (brand_dir / "fonts" / "T.ttf").write_bytes(b"x")
    directory = tmp_path / "versao-1"
    (directory / "stems").mkdir(parents=True)
    (directory / "stems" / "A2-voz.wav").write_bytes(b"x")
    settings = Settings(env="test", data_dir=tmp_path, library_dir=library_dir)
    return Env(tmp_path, calls, library, brand_dir, directory, settings)


def run(env: Env, items: list[FinishItem]) -> tuple[EditPlan, FinishPlan, FinishArtifacts]:
    plan = EditPlan(items=[cut(0, 100), cut(600, 5000)])
    master = env.tmp / "master.mp4"
    master.write_bytes(b"x")
    finish = FinishPlan(items=items)
    artifacts = apply_finishing(
        finish,
        plan,
        {1: master},
        resolve_style(BRAND),
        env.library,
        env.settings,
        env.tmp / "base",
        env.directory,
        env.brand_dir,
    )
    return plan, finish, artifacts


def test_apply_renders_collects_audio_and_builds_a_valid_fcpxml(env: Env) -> None:
    items = [
        fx(EffectKind.ZOOM, 30, 90, EffectMode.RENDERIZADO, "zoom-30", params={"escala": 1.2}),
        fx(EffectKind.CONTADOR_MORTES, 100, 180, EffectMode.RENDERIZADO, "contador-100", params={"ordem": 1}),
        fx(EffectKind.CONTADOR_MORTES, 700, 180, EffectMode.EDITAVEL, "contador-700", params={"ordem": 2}),
        fx(EffectKind.SFX, 200, 0, EffectMode.EDITAVEL, "sfx-200", asset="boom", params={"ganho_db": -7}),
        fx(EffectKind.MUSICA, 0, 1200, EffectMode.RENDERIZADO, "musica-1", asset="tema"),
        fx(EffectKind.COR_LUT, 0, 1200, EffectMode.EDITAVEL, "cor_lut-0", params={"lut": "luts/serie.cube"}),
    ]
    plan, _, art = run(env, items)
    labels = sorted(label for label, _ in env.calls)
    assert labels == ["a", "o", "v"]
    assert set(art.layers.rendered) == {"zoom-30", "contador-100"}
    assert art.layers.rendered_frames == {"zoom-30": 90, "contador-100": 180}
    assert art.layers.texts == {"contador-700": "Mortes: 2"}
    assert art.layers.audio["boom"].frames == 60
    assert art.layers.font == "Titulo" and art.layers.font_color == "1.000 0.502 0.000 1"
    assert art.music_stem is not None and art.music_stem.name == "A4-musica.wav"
    assert any("mais curta que o capítulo" in w for w in art.warnings)  # tema tem 5 s e o capítulo 20 s

    assert art.lut_lua is not None and (art.lut_lua.parent / "luts" / "serie.cube").is_file()
    assert "SetLUT" in art.lut_lua.read_text(encoding="utf-8")

    media = ExportMedia(
        {1: MediaFileInfo(env.tmp / "master.mp4", 20000)},
        {},
        {
            "A1": env.tmp / "A1.wav",
            "A2": env.directory / "stems" / "A2-voz.wav",
            "A4": art.music_stem,
        },
        plan.total_frames,
    )
    (env.tmp / "A1.wav").write_bytes(b"x")
    xml = render_plan_fcpxml(plan, media, "t", art.layers)
    assert check_plan_fcpxml(xml, plan) == []
    lanes = {c.get("lane") for c in ET.fromstring(xml).iter() if c.get("lane")}
    assert {"1", "3", "-4", "-5"} <= lanes


def test_effects_describe_where_and_how_to_undo(env: Env) -> None:
    items = [
        fx(EffectKind.ZOOM, 30, 90, EffectMode.RENDERIZADO, "zoom-30"),
        fx(EffectKind.SHAKE, 400, 36, EffectMode.SUGERIR, "shake-400"),
        fx(EffectKind.ZOOM, 9000, 90, EffectMode.RENDERIZADO, "zoom-fora"),
    ]
    _, finish, art = run(env, items)
    rows = {str(r["id"]): r for r in art.effects}
    assert rows["zoom-30"]["como"] == "renderizado na V2" and "V2" in str(rows["zoom-30"]["desfazer"])
    assert str(rows["shake-400"]["como"]).startswith("só marcador")
    assert "não gerado" in str(rows["zoom-fora"]["como"])  # sem corte ao vivo sob o efeito
    text = leia_me_section(finish, art)
    assert "**zoom**: 2 em modo renderizado" in text and "Desfazer:" in text
    assert "nenhum efeito" not in text.lower()


def test_missing_library_item_and_missing_lut_only_warn(env: Env) -> None:
    items = [
        fx(EffectKind.SFX, 50, 0, EffectMode.EDITAVEL, "sfx-x", asset="nao-existe"),
        fx(EffectKind.COR_LUT, 0, 1200, EffectMode.EDITAVEL, "cor_lut-0", params={"lut": "luts/falta.cube"}),
    ]
    _, _, art = run(env, items)
    assert art.layers.audio == {} and art.lut_lua is None
    joined = "\n".join(art.warnings)
    assert "nao-existe" in joined and "falta.cube" in joined


def test_lua_lut_is_one_line_without_io(tmp_path: Path) -> None:
    lua = lua_lut(tmp_path / "a b" / "s.cube")
    assert "\n" not in lua and "SetLUT(1," in lua and "io." not in lua and "dofile" not in lua


def test_leia_me_without_effects() -> None:
    from cronista.finishing.apply import FinishArtifacts

    plan = FinishPlan()
    assert "Nenhum efeito" in leia_me_section(plan, FinishArtifacts(FinishLayers(plan)))


def test_apply_decisions_removes_and_promotes() -> None:
    plan = FinishPlan(
        items=[
            fx(EffectKind.SHAKE, 10, 36, EffectMode.SUGERIR, "shake"),
            fx(EffectKind.FREEZE_TEXTO, 50, 90, EffectMode.SUGERIR, "freeze"),
            fx(EffectKind.ZOOM, 100, 90, EffectMode.EDITAVEL, "zoom"),
            fx(EffectKind.SFX, 200, 0, EffectMode.EDITAVEL, "sfx", asset="boom"),
        ],
        warnings=["w"],
        input_hash="h",
    )
    out = apply_decisions(
        plan,
        {
            "shake@m": "aceito",
            "freeze@m": "aceito",
            "zoom@m": "removido",
            "sfx@m": "aceito",
            "zoom@outro-momento": "removido",  # de outro momento: não vale aqui
        },
    )
    modes = {i.id: i.mode for i in out.items}
    assert modes == {
        "shake": EffectMode.EDITAVEL,
        "freeze": EffectMode.SUGERIR,  # sem forma editável
        "sfx": EffectMode.EDITAVEL,
    }
    assert out.input_hash == "h" and any("freeze_texto" in w for w in out.warnings)
    assert plan.items[0].mode == EffectMode.SUGERIR  # o plano original não muda

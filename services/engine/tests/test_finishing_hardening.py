"""Correções da revisão de código da Fase 8: escrita atômica, áudio ilegível e cache de exportação."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile

from cronista.domain.tracks import Track as FxTrack
from cronista.finishing.apply import inputs_digest
from cronista.finishing.effects import EffectKind, EffectMode
from cronista.finishing.library import Library, LibraryItem
from cronista.finishing.plan import FinishItem, FinishPlan, decision_key
from cronista.finishing.render.atomic import render_to
from tests.test_finishing_apply import BRAND, Env, env, fx, run  # noqa: F401
from tests.test_finishing_package import BRAND as PACKAGE_BRAND  # noqa: F401
from tests.test_finishing_package import export, setup  # noqa: F401


def test_render_to_publishes_only_a_complete_file(tmp_path: Path) -> None:
    target = tmp_path / "clip.mp4"

    def write(out: Path) -> None:
        out.write_bytes(b"ok")

    render_to(target, write)
    assert target.read_bytes() == b"ok" and not list(tmp_path.glob("part-*"))


def test_render_to_failure_leaves_neither_target_nor_partial(tmp_path: Path) -> None:
    target = tmp_path / "clip.mp4"

    def broken(out: Path) -> None:
        out.write_bytes(b"meio")
        raise RuntimeError("ffmpeg morreu")

    with pytest.raises(RuntimeError):
        render_to(target, broken)
    assert not target.exists() and not list(tmp_path.glob("part-*"))


def test_render_to_keeps_the_extension_for_ffmpeg(tmp_path: Path) -> None:
    seen: list[str] = []

    def write(out: Path) -> None:
        seen.append(out.suffix)
        out.write_bytes(b"x")

    render_to(tmp_path / "x.mov", write)
    assert seen == [".mov"]


def test_unreadable_library_audio_is_a_warning_not_a_crash(env: Env) -> None:  # noqa: F811
    (Path(env.settings.library_dir or "") / "quebrado.wav").write_bytes(b"isto nao e um wav")
    env.library.items.append(
        LibraryItem(id="quebrado", file="quebrado.wav", kind="sfx", origin="propria", license="propria")
    )
    items = [
        fx(EffectKind.SFX, 100, 0, EffectMode.EDITAVEL, "sfx-100", asset="quebrado"),
        fx(EffectKind.SFX, 300, 0, EffectMode.EDITAVEL, "sfx-300", asset="boom"),
    ]
    _, _, art = run(env, items)
    assert set(art.layers.audio) == {"boom"}
    assert any("quebrado" in w and "não consegui ler" in w for w in art.warnings)


def finish_with(asset: str | None = None) -> FinishPlan:
    return FinishPlan(
        items=[
            FinishItem(
                "sfx-1", EffectKind.SFX, EffectMode.EDITAVEL, FxTrack.A5, 10, 0, 0.5, 1, "m", asset, {}, "t"
            )
        ]
    )


def test_inputs_digest_changes_with_brand_files_and_library_files(env: Env) -> None:  # noqa: F811
    from cronista.finishing.brand import resolve_style

    style = resolve_style(BRAND)
    finish = finish_with("boom")
    base = inputs_digest(finish, style, env.brand_dir, env.library, env.settings.library_dir)
    assert base == inputs_digest(finish, style, env.brand_dir, env.library, env.settings.library_dir)

    (env.brand_dir / "luts" / "serie.cube").write_text("LUT_3D_SIZE 33 outro conteudo", encoding="utf-8")
    after_lut = inputs_digest(finish, style, env.brand_dir, env.library, env.settings.library_dir)
    assert after_lut != base

    soundfile.write(
        str(Path(env.settings.library_dir or "") / "boom.wav"), np.zeros(96000, dtype="float32"), 48000
    )
    assert inputs_digest(finish, style, env.brand_dir, env.library, env.settings.library_dir) != after_lut

    other = style.model_copy(
        update={
            "brand": style.brand.model_copy(
                update={
                    "visual": style.brand.visual.model_copy(
                        update={"fonts": style.brand.visual.fonts.model_copy(update={"title": "Outra"})}
                    )
                }
            )
        }
    )
    assert inputs_digest(finish, other, env.brand_dir, env.library, env.settings.library_dir) != after_lut


def test_changing_the_lut_file_makes_a_new_package_version(setup: dict[str, Any]) -> None:  # noqa: F811
    first = export(setup)
    assert export(setup).reused
    lut = Path(setup["settings"].brand_dir) / "luts" / "serie.cube"
    lut.write_text("LUT_3D_SIZE 2 trocado", encoding="utf-8")
    third = export(setup)
    assert not third.reused and third.version == first.version + 1
    manifest = json.loads((third.directory / "manifesto.json").read_text(encoding="utf-8"))
    assert manifest["problemas"] == []


def test_decision_key_joins_id_and_moment() -> None:
    item = FinishItem(
        "zoom-1200",
        EffectKind.ZOOM,
        EffectMode.EDITAVEL,
        FxTrack.V2,
        1200,
        90,
        0.5,
        1,
        "1:s7:1200",
        None,
        {},
        "t",
    )
    assert decision_key(item) == "zoom-1200@1:s7:1200"
    assert Library().items == []

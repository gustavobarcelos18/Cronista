from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from cronista.cli import app
from cronista.config import find_repo_root
from cronista.finishing.brand import (
    DEFAULT_EFFECTS,
    BrandKit,
    EffectPolicy,
    SeriesStyle,
    check_brand_files,
    load_brand_kit,
    load_series_style,
    render_schemas,
    resolve_style,
)
from cronista.finishing.effects import EffectKind, EffectMode
from cronista.finishing.library import (
    Library,
    LibraryItem,
    check_brand_references,
    check_library,
    load_library,
)

ROOT = find_repo_root(Path(__file__))
BRAND = ROOT / "packages" / "brand-kit"

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


def make_brand(**sonic: object) -> BrandKit:
    return BrandKit.model_validate({"name": "t", "visual": VISUAL, "sonic": sonic})


def item(item_id: str, **extra: object) -> LibraryItem:
    base: dict[str, object] = {
        "id": item_id,
        "file": f"{item_id}.wav",
        "kind": "sfx",
        "origin": "propria",
        "license": "propria",
    }
    return LibraryItem.model_validate({**base, **extra})


def test_example_brand_kit_and_series_load() -> None:
    brand = load_brand_kit(BRAND)
    series = load_series_style(BRAND, "exemplo")
    assert brand.visual.day_card.template == "Dia {n}"
    assert check_brand_files(brand, BRAND, series) == []
    resolved = resolve_style(brand, series)
    assert resolved.brand.visual.palette.accent == "#3FA7D6"
    assert resolved.brand.visual.palette.primary == brand.visual.palette.primary


def test_schemas_in_repo_are_up_to_date() -> None:
    for name, text in render_schemas().items():
        stored = BRAND / name
        assert stored.is_file(), f"rode `uv run python -m cronista.finishing.brand` ({name} ausente)"
        assert json.loads(stored.read_text(encoding="utf-8")) == json.loads(text), f"{name} defasado"


def test_invalid_color_and_template_rejected() -> None:
    bad = {**VISUAL, "palette": {**VISUAL["palette"], "primary": "vermelho"}}
    with pytest.raises(ValidationError):
        BrandKit.model_validate({"name": "t", "visual": bad})
    with pytest.raises(ValidationError, match="template"):
        BrandKit.model_validate({"name": "t", "visual": {**VISUAL, "day_card": {"template": "Dia"}}})


def test_unknown_field_rejected() -> None:
    with pytest.raises(ValidationError):
        BrandKit.model_validate({"name": "t", "visual": VISUAL, "extra": 1})


def test_default_effects_cover_every_kind_and_are_conservative() -> None:
    assert set(DEFAULT_EFFECTS) == set(EffectKind)
    # Humor e impacto nunca nascem aplicados: o criador liga por série.
    for kind in (EffectKind.SFX_MEME, EffectKind.PIADA_VISUAL, EffectKind.SHAKE, EffectKind.FREEZE_TEXTO):
        assert DEFAULT_EFFECTS[kind].mode is EffectMode.SUGERIR


def test_series_overrides_only_what_changes() -> None:
    brand = make_brand(mood_themes={"tenso": ["t1"]})
    series = SeriesStyle(
        name="s",
        palette={"accent": "#ABCDEF"},
        mood_themes={"calmo": ["c1"]},
        effects={EffectKind.ZOOM: EffectPolicy(mode=EffectMode.RENDERIZADO, max_per_minute=1)},
        max_effects_per_minute=3,
    )
    resolved = resolve_style(brand, series)
    assert resolved.brand.visual.palette.accent == "#ABCDEF"
    assert resolved.brand.visual.palette.text == "#FFFFFF"
    assert resolved.brand.sonic.mood_themes == {"tenso": ["t1"], "calmo": ["c1"]}
    assert resolved.policy(EffectKind.ZOOM).mode is EffectMode.RENDERIZADO
    assert resolved.policy(EffectKind.SFX) == DEFAULT_EFFECTS[EffectKind.SFX]
    assert resolved.max_effects_per_minute == 3
    assert brand.visual.palette.accent == "#334455"  # o brand kit original fica intacto


def test_resolve_without_series_uses_defaults() -> None:
    resolved = resolve_style(make_brand())
    assert resolved.series == "" and resolved.effects == DEFAULT_EFFECTS


def test_series_empty_mood_rejected() -> None:
    with pytest.raises(ValidationError, match="sem nenhuma trilha"):
        SeriesStyle(name="s", mood_themes={"tenso": []})


def test_brand_files_missing_and_escaping(tmp_path: Path) -> None:
    brand = BrandKit.model_validate(
        {"name": "t", "visual": {**VISUAL, "lut": "luts/x.cube", "frames": ["../fora.png"]}}
    )
    problems = check_brand_files(brand, tmp_path)
    assert any("LUT" in p and "não existe" in p for p in problems)
    assert any("sai da pasta" in p for p in problems)
    (tmp_path / "luts").mkdir()
    (tmp_path / "luts" / "x.cube").write_text("LUT", encoding="utf-8")
    assert not any("LUT" in p for p in check_brand_files(brand, tmp_path))


def test_series_name_must_be_safe() -> None:
    with pytest.raises(ValueError, match="inválido"):
        load_series_style(BRAND, "../brand")


def test_music_needs_bpm_and_ids_are_unique() -> None:
    with pytest.raises(ValidationError, match="bpm"):
        item("m1", kind="musica")
    with pytest.raises(ValidationError, match="repetidos"):
        Library(items=[item("a"), item("a")])


def test_library_requires_origin_and_license() -> None:
    with pytest.raises(ValidationError):
        LibraryItem.model_validate({"id": "a", "file": "a.wav", "kind": "sfx", "origin": "x", "license": ""})


def test_library_find_is_deterministic_and_filters() -> None:
    lib = Library(
        items=[
            item("b", tags=["morte", "impacto"]),
            item("a", tags=["morte"]),
            item("c", tags=["morte"], commercial_use=False),
            item("m", kind="musica", bpm=90, mood="tenso"),
        ]
    )
    assert [i.id for i in lib.find("sfx", tags={"morte"})] == ["a", "b"]
    assert [i.id for i in lib.find("sfx", tags={"morte"}, commercial=False)] == ["a", "b", "c"]
    assert [i.id for i in lib.find("musica", mood="tenso")] == ["m"]
    assert lib.find("meme") == []


def test_check_library_reports_missing_unlisted_and_bad_format(tmp_path: Path) -> None:
    (tmp_path / "a.wav").write_bytes(b"x")
    (tmp_path / "sobra.mp3").write_bytes(b"x")
    (tmp_path / "notas.txt").write_text("não é mídia", encoding="utf-8")
    lib = Library(
        items=[item("a"), item("falta"), item("ruim", file="ruim.xyz"), item("fora", file="../fora.wav")]
    )
    (tmp_path / "ruim.xyz").write_bytes(b"x")
    problems = check_library(lib, tmp_path)
    assert any(p.startswith("falta:") and "não existe" in p for p in problems)
    assert any(p.startswith("ruim:") and "formato" in p for p in problems)
    assert any(p.startswith("fora:") and "sai da pasta" in p for p in problems)
    assert any("sobra.mp3" in p and "sem registro" in p for p in problems)
    assert not any("notas.txt" in p or p.startswith("a:") for p in problems)


def test_brand_references_checked_against_library() -> None:
    brand = make_brand(death_sound="som", mood_themes={"tenso": ["trilha", "nada"]})
    lib = Library(
        items=[item("som"), item("trilha", kind="musica", bpm=90, commercial_use=False)],
    )
    problems = check_brand_references(brand, lib)
    assert any("'nada'" in p and "não está" in p for p in problems)
    assert any("'trilha'" in p and "comercial" in p for p in problems)
    assert not any("'som'" in p for p in problems)


def test_load_library_missing_inventory(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="inventário"):
        load_library(tmp_path)


def test_load_library_example_is_valid(tmp_path: Path) -> None:
    (tmp_path / "inventario.yaml").write_text(
        (BRAND / "inventario.exemplo.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    loaded = load_library(tmp_path)
    assert {i.id for i in loaded.items} == {"som-morte", "trilha-tensa-01"}
    assert loaded.get("trilha-tensa-01") is not None


def test_cli_brand_check_ok_and_series_listing() -> None:
    result = CliRunner().invoke(app, ["brand-check", "--serie", "exemplo"])
    assert result.exit_code == 0, result.output
    assert "zoom" in result.output and "ok" in result.output


def test_cli_brand_check_unknown_series_fails() -> None:
    result = CliRunner().invoke(app, ["brand-check", "--serie", "nao-existe"])
    assert result.exit_code == 1


def test_lut_is_a_suggestion_by_default() -> None:
    """C6 (auditoria 10A): o `SetLUT` do gratuito falhou no spike; o padrão não promete aplicar."""
    from cronista.finishing.brand import DEFAULT_EFFECTS
    from cronista.finishing.effects import EffectKind, EffectMode

    assert DEFAULT_EFFECTS[EffectKind.COR_LUT].mode == EffectMode.SUGERIR

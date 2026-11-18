"""`export_montagem` com acabamento, de ponta a ponta, sem FFmpeg: banco, mixagem e render são simulados."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from cronista.assembly.plan import EditItem, EditPlan, Mode
from cronista.config import Settings
from cronista.domain.tracks import Track
from cronista.export import pacote
from cronista.finishing.brand import BrandKit, EffectPolicy, SeriesStyle, resolve_style
from cronista.finishing.effects import EffectKind, EffectMode
from cronista.mix.service import MixReport
from cronista.montage import SourceFile

BRAND = BrandKit.model_validate(
    {
        "name": "t",
        "visual": {
            "palette": {
                "primary": "#112233",
                "secondary": "#223344",
                "accent": "#334455",
                "background": "#101010",
                "text": "#FFFFFF",
            },
            "fonts": {"title": "T", "body": "B"},
            "lut": "luts/serie.cube",
        },
    }
)


def cut(start: int, in_frame: int) -> EditItem:
    return EditItem(
        file_id=1,
        in_frame=in_frame,
        out_frame=in_frame + 3600,
        track=Track.V1,
        mode=Mode.AO_VIVO,
        speed=1,
        reason="t",
        chapter=1,
        beat="falha",
        segment_id=f"s{start}",
        score=0.95,
        timeline_start=start,
    )


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    master = tmp_path / "master.mp4"
    master.write_bytes(b"x")
    plan = EditPlan(items=[cut(0, 100), cut(3600, 9000)])
    brand_dir = tmp_path / "brand"
    (brand_dir / "luts").mkdir(parents=True)
    (brand_dir / "luts" / "serie.cube").write_text("LUT_3D_SIZE 2", encoding="utf-8")

    def fake_mix(*args: Any, **kwargs: Any) -> MixReport:
        stems = args[6]
        stems.mkdir(parents=True, exist_ok=True)
        for name in ("A1-jogo", "A2-voz", "A6-jogo-cru", "A7-microfone-cru"):
            (stems / f"{name}.wav").write_bytes(b"x")
        return MixReport(stems)

    session = SimpleNamespace(media_files=[SimpleNamespace(id=1)])
    db = SimpleNamespace(get=lambda *_: session, scalars=lambda *_: [])
    monkeypatch.setattr(pacote, "assemble", lambda *a, **k: (plan, SimpleNamespace(chapters=[])))
    monkeypatch.setattr(pacote, "load_source", lambda *_: SourceFile(1, master, 400.0, None, None))
    monkeypatch.setattr(pacote, "render_timelapses", lambda *a, **k: {})
    monkeypatch.setattr(pacote, "mix_session", fake_mix)

    def fake_ffmpeg(_s: Settings, args: list[str]) -> None:
        Path(args[-1]).write_bytes(b"x")

    monkeypatch.setattr("cronista.finishing.render.video.run_ffmpeg", fake_ffmpeg)
    settings = Settings(env="test", data_dir=tmp_path / "data", brand_dir=brand_dir)
    # O LUT é `sugerir` por padrão (SetLUT não confirmado no gratuito, §60): a série o liga como `editavel`.
    series = SeriesStyle(name="teste", effects={EffectKind.COR_LUT: EffectPolicy(mode=EffectMode.EDITAVEL)})
    return {"db": db, "settings": settings, "base": tmp_path / "out", "style": resolve_style(BRAND, series)}


def export(setup: dict[str, Any], **kwargs: Any) -> pacote.PackageReport:
    return pacote.export_montagem(
        setup["db"], 1, setup["settings"], out_base=setup["base"], style=setup["style"], **kwargs
    )


def test_package_carries_finishing_files_manifest_and_guide(setup: dict[str, Any]) -> None:
    report = export(setup)
    d = report.directory
    assert report.problems == [] and not report.reused
    manifest = json.loads((d / "manifesto.json").read_text(encoding="utf-8"))
    kinds = {e["efeito"] for e in manifest["efeitos"]}
    assert "zoom" in kinds and "cor_lut" in kinds
    assert all(e["desfazer"] for e in manifest["efeitos"])
    assert (d / "acabamento.json").is_file() and (d / "lut-aplicar.lua").is_file()
    assert (d / "luts" / "serie.cube").is_file()
    guide = (d / "LEIA-ME.md").read_text(encoding="utf-8")
    assert "## Acabamento (Fase 8)" in guide and "lut-aplicar.lua" in guide
    fcpxml = (d / "montagem.fcpxml").read_text(encoding="utf-8")
    assert 'lane="1"' in fcpxml  # zoom editável na V2


def test_same_input_is_reused_and_a_decision_makes_a_new_version(setup: dict[str, Any]) -> None:
    first = export(setup)
    again = export(setup)
    assert again.reused and again.version == first.version

    zoom = next(
        f"{e['id']}@{e['momento']}"
        for e in json.loads((first.directory / "manifesto.json").read_text(encoding="utf-8"))["efeitos"]
        if e["efeito"] == "zoom"
    )
    decided = export(setup, finish_decisions={zoom: "removido"})
    assert not decided.reused and decided.version == first.version + 1
    kinds = {
        e["id"]
        for e in json.loads((decided.directory / "manifesto.json").read_text(encoding="utf-8"))["efeitos"]
    }
    assert zoom.split("@")[0] not in kinds
    assert (first.directory / "montagem.fcpxml").is_file()  # a versão anterior continua lá


def test_without_style_the_package_has_no_finishing(setup: dict[str, Any]) -> None:
    report = pacote.export_montagem(setup["db"], 1, setup["settings"], out_base=setup["base"])
    manifest = json.loads((report.directory / "manifesto.json").read_text(encoding="utf-8"))
    assert manifest["acabamento"] is None and manifest["efeitos"] == []
    assert not (report.directory / "acabamento.json").exists()
    assert "Acabamento (Fase 8)" not in (report.directory / "LEIA-ME.md").read_text(encoding="utf-8")

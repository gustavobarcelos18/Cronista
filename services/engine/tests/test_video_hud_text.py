"""OCR do HUD (3C-3): etapa com leitor falso sobre um master sintético; sem RapidOCR nem GPU."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from cronista.audio.events import events_from_result
from cronista.config import Settings
from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource
from cronista.domain.models import StageResult
from cronista.pipeline import StageContext
from cronista.video import frames as vframes
from cronista.video.broll import Candidate, theme_tags
from cronista.video.hud_text import HudTextStage, clean, crop, merge_reads
from cronista.video.ports import HudRegionSpec, RgbFrames, VideoModels
from cronista.video.stages import video_stages
from tests.fakes_video import FakeEmbedder


class FakeReader:
    """Devolve o texto pela cor do recorte: azul = BIOMA A, vermelho = BIOMA B."""

    name = "fake-ocr"
    version = "1"

    def __init__(self) -> None:
        self.options: dict[str, Any] = {}
        self.calls = 0

    def read(self, crops: Sequence[RgbFrames]) -> list[str]:
        self.calls += 1
        return ["bioma a" if c[..., 2].mean() > c[..., 0].mean() else " Bioma  B 12 " for c in crops]


def _master(settings: Settings, path: Path) -> None:
    subprocess.run(
        [
            settings.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=30:d=10",
            "-f", "lavfi", "-i", "color=c=red:s=640x360:r=30:d=10",
            "-filter_complex", "[0][1]concat=n=2:v=1:a=0", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )  # fmt: skip


def test_clean_and_merge() -> None:
    assert clean("  a   b ", "text") == "a b"
    assert clean("X: 12,5 m", "number") == ":12,5"
    merged = merge_reads([(0, "a"), (5, "a"), (10, ""), (15, "b"), (20, "b")], 5)
    assert merged == [(0, 10, "a"), (15, 25, "b")]


def test_crop_relative() -> None:
    frame = np.zeros((100, 200, 3), np.uint8)
    out = crop(frame, HudRegionSpec("r", 0.5, 0.1, 0.25, 0.2))
    assert out.shape == (20, 50, 3)


def test_stage_reads_only_declared_regions(tmp_path: Path, settings: Settings) -> None:
    master = tmp_path / "m.mp4"
    _master(settings, master)
    out = tmp_path / "out"
    out.mkdir()
    original = tmp_path / "original-interrompido.mp4"  # o OCR precisa ler o master normalizado, não este
    original.write_bytes(b"x")
    ctx = StageContext(
        media_path=original,
        out_dir=out,
        settings=settings,
        inputs={"normalize": StageResult(data={"media": str(master)})},
    )
    reader = FakeReader()
    regions = (
        HudRegionSpec("bioma", 0.1, 0.1, 0.3, 0.1, "text", tag_theme=True),
        HudRegionSpec("icone", 0.5, 0.5, 0.1, 0.1, "icon"),
    )
    result = HudTextStage(reader, regions, every_s=5).run(ctx)
    events = events_from_result(result) or []
    assert [(e.evidence.quote, e.evidence.start_frame, e.evidence.end_frame) for e in events] == [
        ("bioma a", 0, 600),
        ("Bioma B 12", 600, 1200),
    ]
    assert events[0].payload == {"regiao": "bioma", "texto": "bioma a", "tag_tema": True}
    assert any("icone" in w for w in result.warnings)


def test_stage_without_regions_reads_nothing(tmp_path: Path, settings: Settings) -> None:
    out = tmp_path / "o"
    out.mkdir()
    reader = FakeReader()
    ctx = StageContext(media_path=tmp_path / "nao-existe.mp4", out_dir=out, settings=settings, inputs={})
    result = HudTextStage(reader, ()).run(ctx)
    assert result.data["count"] == 0 and reader.calls == 0


def test_spans_limit_reading(tmp_path: Path, settings: Settings) -> None:
    master = tmp_path / "m.mp4"
    _master(settings, master)
    seconds = [s for s, _ in vframes.iter_frames_every(settings, master, every_s=5, start_s=10, end_s=20)]
    assert seconds == [10.0, 15.0]


def test_theme_tags_from_hud_text() -> None:
    def ev(a: int, b: int, text: str, theme: bool) -> AnalysisEvent:
        e = Evidence(source=EvidenceSource.CENA, start_frame=a, end_frame=b, confidence=0.5,
                     model="m", model_version="1", params_hash="h", quote=text)  # fmt: skip
        return AnalysisEvent(kind="hud_texto", evidence=e, payload={"texto": text, "tag_tema": theme})

    cand = Candidate(100, 400, "parada", 0.0)
    texts = [ev(0, 200, "Spider Caves", True), ev(0, 200, "x: 1", False), ev(500, 600, "Plains", True)]
    assert theme_tags(cand, texts) == ["spider_caves"]


def test_video_stages_include_hud_text_only_with_reader_and_regions() -> None:
    region = HudRegionSpec("b", 0, 0, 0.1, 0.1)
    names = [s.name for s in video_stages(VideoModels(hud_reader=FakeReader(), hud_regions=(region,)))]
    assert "video_hud_text" in names
    assert "video_hud_text" not in [s.name for s in video_stages(VideoModels(hud_reader=FakeReader()))]
    models = VideoModels(embedder=FakeEmbedder(), hud_reader=FakeReader(), hud_regions=(region,))
    broll = next(s for s in video_stages(models) if s.name == "video_broll")
    assert "video_hud_text" in broll.needs

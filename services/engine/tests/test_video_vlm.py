"""VLM em perguntas fechadas (3C-4): validação das respostas e a etapa de nomes de menu, com VLM falso."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pytest

from cronista.audio.events import events_from_result
from cronista.config import Settings
from cronista.domain.models import StageResult
from cronista.pipeline import StageContext
from cronista.video.ports import RgbImage, VideoModels
from cronista.video.stages import video_stages
from cronista.video.vlm import (
    ENEMY_PRESENT,
    MENU_KIND,
    MenuNamesStage,
    answer_model,
    ask_choice,
    parse_answer,
)
from tests.fakes_video import FakeEmbedder

CHOICES = ("inventory", "map", "other")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"answer": "map"}', "map"),
        ('Sure! {"answer": "inventory"} done', "inventory"),
        ('{"answer": "banana"}', None),  # fora das opções
        ("It looks like an Inventory screen.", "inventory"),
        ("inventory or map", None),  # ambíguo: duas opções
        ("", None),
        ("{quebrado", None),
    ],
)
def test_parse_answer(raw: str, expected: str | None) -> None:
    assert parse_answer(raw, CHOICES) == expected


def test_schema_lists_choices() -> None:
    schema = MENU_KIND.schema()
    assert set(schema["properties"]["answer"]["enum"]) == set(MENU_KIND.choices)
    assert answer_model(("yes", "no")).model_validate({"answer": "yes"})
    assert all(c in MENU_KIND.prompt() for c in MENU_KIND.choices)


class FakeVLM:
    name = "fake-vlm"
    version = "1"
    options: ClassVar[dict[str, Any]] = {}

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.prompts: list[str] = []

    def ask(self, image: RgbImage, prompt: str, max_new_tokens: int = 24) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0)


def test_ask_choice_uses_closed_prompt() -> None:
    vlm = FakeVLM(['{"answer": "yes"}'])
    assert ask_choice(vlm, np.zeros((4, 4, 3), np.uint8), ENEMY_PRESENT) == "yes"
    assert '"yes", "no"' in vlm.prompts[0]


def _proxy(settings: Settings, path: Path) -> None:
    subprocess.run(
        [settings.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "color=c=gray:s=320x180:r=30:d=4", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )  # fmt: skip


def test_menu_names_one_question_per_type(tmp_path: Path, settings: Settings) -> None:
    proxy = tmp_path / "p.mp4"
    _proxy(settings, proxy)
    types = [
        {"id": 0, "menus": 5, "seconds": 30.0, "representative_frame": 60},
        {"id": 1, "menus": 2, "seconds": 9.0, "representative_frame": 120},
        {"id": 2, "menus": 1, "seconds": 4.0, "representative_frame": 180},
    ]
    out = tmp_path / "out"
    out.mkdir()
    ctx = StageContext(
        media_path=tmp_path / "m.mp4",
        out_dir=out,
        settings=settings,
        inputs={
            "proxy": StageResult(data={"proxy": str(proxy)}),
            "video_menu_types": StageResult(data={"types": types}),
        },
    )
    vlm = FakeVLM(['{"answer": "inventory"}', "sem ideia", '{"answer": "map"}'])
    result = MenuNamesStage(vlm).run(ctx)
    events = events_from_result(result) or []
    assert len(vlm.prompts) == 3  # uma pergunta por tipo, não por menu
    assert [(e.payload["tipo_id"], e.payload["nome"]) for e in events] == [(0, "inventory"), (2, "map")]
    assert any("inválida" in w for w in result.warnings)


def test_stage_only_with_vlm() -> None:
    models = VideoModels(embedder=FakeEmbedder(), vlm=FakeVLM([]))
    assert "video_menu_names" in [s.name for s in video_stages(models)]
    assert "video_menu_names" not in [s.name for s in video_stages(VideoModels(embedder=FakeEmbedder()))]

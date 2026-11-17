from __future__ import annotations

from pathlib import Path

from cronista.audio.annotate_ui import build_suggestions, render_annotator


def test_sugestoes_filtram_classe_e_confianca() -> None:
    events = [
        ("fala", 60, 120, 0.9, "olá"),
        ("risada", 600, 660, 0.2, None),
        ("risada", 600, 660, 0.8, None),
        ("cena", 0, 10, 1.0, None),
    ]
    sug = build_suggestions(events)
    assert [s["cls"] for s in sug] == ["fala", "risada"]
    assert sug[0]["start"] == 1.0 and sug[0]["note"] == "olá"


def test_pagina_embute_dados_sem_quebrar_script(tmp_path: Path) -> None:
    page = render_annotator(
        tmp_path / "p.mp4", [{"cls": "fala", "start": 0, "end": 1, "note": "</script>"}], "x"
    )
    assert "</script>" not in page.split("const D=")[1].split("\n")[0]


def test_saved_rows_key_depends_on_mode_and_suggestions(tmp_path: Path) -> None:
    import re

    from cronista.audio.annotate_ui import render_annotator

    video = tmp_path / "v.mp4"
    sug_a: list[dict[str, object]] = [{"cls": "menu", "start": 1.0, "end": 5.0, "note": "", "conf": 0.5}]
    sug_b: list[dict[str, object]] = [{"cls": "menu", "start": 2.0, "end": 6.0, "note": "", "conf": 0.5}]

    def key(page: str) -> str:
        match = re.search(r'"key": "([^"]+)"', page)
        assert match
        return match.group(1)

    audio = key(render_annotator(video, sug_a, "t", "audio"))
    visual = key(render_annotator(video, sug_a, "t", "visual"))
    regenerated = key(render_annotator(video, sug_b, "t", "visual"))
    assert len({audio, visual, regenerated}) == 3

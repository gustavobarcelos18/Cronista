from __future__ import annotations

from cronista.audio.annotate_ui import VISUAL_CLASSES_UI, build_suggestions
from cronista.domain.frames import FPS
from cronista.gabarito import CLASSES, Annotation
from cronista.video.quality import evaluate_video, match_pairs, render_video_quality


def ann(cls: str, a: float, b: float) -> Annotation:
    return Annotation(1, round(a * FPS), round(b * FPS), cls, "")


def iv(a: float, b: float) -> tuple[int, int]:
    return round(a * FPS), round(b * FPS)


def test_hud_oculto_is_a_gabarito_class() -> None:
    assert "hud_oculto" in CLASSES


def test_match_pairs_prefers_largest_overlap() -> None:
    pairs = match_pairs([iv(10, 20)], [iv(0, 11), iv(12, 19)], tolerance=0)
    assert pairs == [(iv(10, 20), iv(12, 19))]


def test_precision_recall_and_boundary_error() -> None:
    gab = [ann("menu", 10, 20), ann("menu", 100, 110), ann("loading", 50, 55)]
    pred = {"menu": [iv(11, 20), iv(300, 310)], "loading": []}
    by = {r.cls: r for r in evaluate_video(gab, pred, total_frames=30 * 60 * FPS, tolerance_s=2.0)}
    menu = by["menu"]
    assert (menu.expected, menu.predicted, menu.matched) == (2, 2, 1)
    assert menu.precision == 0.5 and menu.recall == 0.5
    assert menu.boundary_err_s is not None and abs(menu.boundary_err_s - 0.5) < 1e-6
    assert menu.within_tolerance == 1 and menu.false_per_30min == 1.0
    assert by["loading"].recall == 0.0 and by["loading"].precision is None
    assert "idle" not in by


def test_render_and_empty() -> None:
    assert "nada a avaliar" in render_video_quality([], 2.0)
    gab = [ann("idle", 0, 12)]
    text = render_video_quality(evaluate_video(gab, {"idle": [iv(0, 12)]}, 60 * FPS), 2.0)
    assert "idle" in text and "1.00" in text


def test_visual_suggestions_carry_thumbnails_and_skip_audio() -> None:
    events: list[tuple[str, int, int, float, str | None]] = [
        ("menu", 0, 600, 0.1, None),
        ("idle", 600, 1200, 0.9, None),
        ("risada", 0, 60, 0.9, None),
    ]
    out = build_suggestions(events, VISUAL_CLASSES_UI, lambda f: f"thumb{f}")
    assert [s["cls"] for s in out] == ["menu", "idle"]  # confiança baixa não corta candidato visual
    assert out[0]["thumb"] == "thumb300"
    assert all(s["cls"] != "menu" for s in build_suggestions(events))

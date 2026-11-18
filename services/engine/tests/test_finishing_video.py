from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

import pytest

from cronista.assembly.plan import EditItem, EditPlan, Mode
from cronista.config import Settings
from cronista.domain.tracks import Track
from cronista.domain.tracks import Track as FxTrack
from cronista.finishing.effects import EffectKind, EffectMode
from cronista.finishing.plan import FinishItem, FinishPlan
from cronista.finishing.render.video import (
    SourceWindow,
    clip_name,
    effect_filter,
    filter_path,
    lut_filter,
    render_video_effects,
    shake_envelope,
    shake_filter,
    source_window,
    zoom_curve,
    zoom_expr,
    zoom_filter,
)


def cut(
    start: int, *, in_frame: int = 100, frames: int = 600, mode: Mode = Mode.AO_VIVO, speed: int = 1
) -> EditItem:
    return EditItem(
        file_id=7,
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
    *,
    mode: EffectMode = EffectMode.RENDERIZADO,
    params: dict[str, float | int | str] | None = None,
    item_id: str | None = None,
) -> FinishItem:
    track = FxTrack.V2 if kind in (EffectKind.ZOOM, EffectKind.SHAKE) else FxTrack.V1
    return FinishItem(
        item_id or f"{kind.value}-{start}",
        kind,
        mode,
        track,
        start,
        frames,
        0.8,
        1,
        "m",
        None,
        params or {},
        "t",
    )


def evaluate(expr: str, on: int) -> float:
    """Roda a expressão do FFmpeg em Python (mesmas funções e constantes) para comparar com a curva."""
    scope = {"pow": pow, "sin": math.sin, "PI": math.pi, "abs": abs, "min": min, "on": on}
    return float(eval(expr, {"__builtins__": {}}, scope))


@pytest.mark.parametrize("easing", ["ease_in_out", "linear"])
def test_zoom_curve_starts_and_ends_at_original_framing(easing: str) -> None:
    assert zoom_curve(0.0, easing) == pytest.approx(0.0, abs=1e-9)
    assert zoom_curve(1.0, easing) == pytest.approx(0.0, abs=1e-9)
    assert zoom_curve(0.5, easing) == pytest.approx(1.0)
    assert zoom_curve(-3, easing) == zoom_curve(0, easing)


@pytest.mark.parametrize("easing", ["ease_in_out", "linear"])
def test_zoom_expression_matches_python_curve(easing: str) -> None:
    n1 = 89
    expr = zoom_expr(easing).replace("{n1}", str(n1))
    for on in (0, 1, 20, 44, 45, 70, 89):
        assert evaluate(expr, on) == pytest.approx(zoom_curve(on / n1, easing), abs=1e-9)


def test_shake_envelope_attacks_fast_and_settles() -> None:
    assert shake_envelope(0.0) == 0.0
    assert shake_envelope(1.0) == 0.0
    assert shake_envelope(0.1) == pytest.approx(0.9)
    assert all(shake_envelope(p / 100) >= shake_envelope((p + 1) / 100) for p in range(10, 100))


def test_zoom_filter_shape() -> None:
    f = zoom_filter(1.15, 90, focus=(0.25, 0.75))
    assert f.startswith("scale=3840:2160:flags=lanczos,zoompan=")
    assert "1+(0.15)*pow(sin(PI*on/89),2)" in f
    assert "(iw-iw/zoom)*0.25" in f and "(ih-ih/zoom)*0.75" in f
    assert f.endswith(":d=1:s=1920x1080:fps=60")


def test_zoom_filter_rejects_zoom_out_and_tiny_clips() -> None:
    with pytest.raises(ValueError):
        zoom_filter(0.9, 90)
    with pytest.raises(ValueError):
        zoom_filter(1.1, 1)


def test_shake_filter_grows_with_amplitude_and_stays_centered() -> None:
    small, big = shake_filter(4, 36), shake_filter(16, 36)
    assert "zoompan=z='1+0.0048*" in small
    assert "zoompan=z='1+0.0192*" in big
    assert "(iw-iw/zoom)/2" in small and "(ih-ih/zoom)/2" in small
    with pytest.raises(ValueError):
        shake_filter(0, 36)


def test_effect_filter_reads_item_params_with_defaults() -> None:
    z = effect_filter(fx(EffectKind.ZOOM, 0, 90, params={"escala": 1.2, "easing": "linear"}), 90)
    assert "(0.2)*(1-abs(2*on/89-1))" in z
    assert effect_filter(fx(EffectKind.SHAKE, 0, 36), 36) == shake_filter(8.0, 36)
    with pytest.raises(ValueError):
        effect_filter(fx(EffectKind.CONTADOR_MORTES, 0, 90), 90)


def test_lut_filter_escapes_windows_paths() -> None:
    assert filter_path(Path("C:/kit/luts/a,b.cube")) == "C\\:/kit/luts/a\\,b.cube"
    assert lut_filter(Path("luts/serie.cube")) == "lut3d=file='luts/serie.cube'"


def test_source_window_maps_timeline_to_recording_frames() -> None:
    plan = EditPlan(items=[cut(0), cut(600, in_frame=5000)])
    assert source_window(plan, fx(EffectKind.ZOOM, 30, 90)) == SourceWindow(7, 130, 90)
    assert source_window(plan, fx(EffectKind.ZOOM, 650, 90)) == SourceWindow(7, 5050, 90)


def test_source_window_trims_at_cut_end_and_skips_non_live() -> None:
    plan = EditPlan(items=[cut(0, frames=100), cut(100, mode=Mode.TIMELAPSE, speed=10, frames=60)])
    assert source_window(plan, fx(EffectKind.ZOOM, 70, 90)) == SourceWindow(7, 170, 30)
    assert source_window(plan, fx(EffectKind.ZOOM, 99, 90)) is None  # sobra 1 quadro
    assert source_window(plan, fx(EffectKind.ZOOM, 120, 30)) is None  # timelapse
    assert source_window(plan, fx(EffectKind.ZOOM, 900, 30)) is None  # fora de qualquer corte


def test_clip_name_changes_with_filter_and_encoder() -> None:
    item, win = fx(EffectKind.ZOOM, 0, 90), SourceWindow(7, 100, 90)
    a = clip_name(item, win, "f1", ["-c:v", "libx264"])
    assert a == clip_name(item, win, "f1", ["-c:v", "libx264"])
    assert a != clip_name(item, win, "f2", ["-c:v", "libx264"])
    assert a != clip_name(item, win, "f1", ["-c:v", "h264_nvenc"])
    assert a.startswith("fx-zoom-7-100-90-") and a.endswith(".mp4")


def test_render_skips_what_is_not_rendered_and_reports_problems(tmp_path: Path) -> None:
    plan = EditPlan(items=[cut(0)])
    finish = FinishPlan(
        items=[
            fx(EffectKind.ZOOM, 10, 90, mode=EffectMode.EDITAVEL, item_id="editavel"),
            fx(EffectKind.ZOOM, 5000, 90, item_id="sem-corte"),
            fx(EffectKind.SHAKE, 20, 36, item_id="sem-mestre"),
            fx(EffectKind.COR_LUT, 0, 600, item_id="lut"),
        ]
    )
    result = render_video_effects(finish, plan, {}, tmp_path / "fx", Settings(env="test", data_dir=tmp_path))
    assert result.clips == {}
    joined = "\n".join(result.warnings)
    assert "sem-corte: sem corte ao vivo" in joined
    assert "sem-mestre: gravação 7 sem arquivo mestre" in joined
    assert "editavel" not in joined
    assert "LUT em modo renderizado" in joined


def test_render_calls_ffmpeg_once_per_clip_and_reuses_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake(_settings: Settings, args: list[str]) -> None:
        calls.append(args)
        Path(args[-1]).write_bytes(b"mp4")

    monkeypatch.setattr("cronista.finishing.render.video.run_ffmpeg", fake)
    plan = EditPlan(items=[cut(0)])
    finish = FinishPlan(items=[fx(EffectKind.ZOOM, 30, 90, params={"escala": 1.2}, item_id="z1")])
    settings = Settings(env="test", data_dir=tmp_path)
    master = tmp_path / "m.mp4"

    first = render_video_effects(finish, plan, {7: master}, tmp_path / "fx", settings)
    again = render_video_effects(finish, plan, {7: master}, tmp_path / "fx", settings)

    assert len(calls) == 1 and first.clips == again.clips and first.warnings == []
    args = calls[0]
    assert args[args.index("-ss") + 1] == f"{130 / 60:.6f}"
    assert args[args.index("-t") + 1] == f"{90 / 60:.6f}"
    assert args[args.index("-frames:v") + 1] == "90" and "-an" in args
    assert args[args.index("-vf") + 1].endswith(",format=yuv420p")


@pytest.mark.media
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="precisa do FFmpeg")
@pytest.mark.parametrize("kind", [EffectKind.ZOOM, EffectKind.SHAKE])
def test_ffmpeg_renders_exact_frame_count(kind: EffectKind, tmp_path: Path) -> None:
    master = tmp_path / "m.mp4"
    source = "testsrc2=size=1920x1080:rate=60:duration=4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            source,
            "-pix_fmt",
            "yuv420p",
            str(master),
        ],
        check=True,
    )
    plan = EditPlan(items=[cut(0, in_frame=30, frames=200)])
    finish = FinishPlan(items=[fx(kind, 20, 90, params={"amplitude_px": 10, "escala": 1.2}, item_id="x")])
    settings = Settings(env="test", data_dir=tmp_path)
    out = render_video_effects(finish, plan, {7: master}, tmp_path / "fx", settings).clips["x"]
    probe = subprocess.run(
        [
            *["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0"],
            *["-show_entries", "stream=nb_read_frames,width,height,r_frame_rate", "-of", "csv=p=0", str(out)],
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    fields = probe.stdout.strip().split(",")
    assert fields[:3] == ["1920", "1080", "60/1"]
    assert fields[3] == "90"

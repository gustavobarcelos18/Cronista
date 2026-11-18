from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile

from cronista.config import Settings
from cronista.domain.tracks import Track
from cronista.finishing.brand import BrandKit
from cronista.finishing.effects import EffectKind, EffectMode
from cronista.finishing.plan import FinishItem, FinishPlan
from cronista.finishing.render.audio import (
    MusicClip,
    audio_frames,
    music_filtergraph,
    music_items,
    render_music_stem,
)
from cronista.finishing.render.overlay import (
    counter_filter,
    counter_position,
    counter_text,
    drawtext_escape,
    ffmpeg_color,
    find_font,
    overlay_name,
    render_overlays,
)

VISUAL = BrandKit.model_validate(
    {
        "name": "t",
        "visual": {
            "palette": {
                "primary": "#112233",
                "secondary": "#223344",
                "accent": "#334455",
                "background": "#101010",
                "text": "#FFEEDD",
            },
            "fonts": {"title": "A", "body": "B", "files": ["fonts/T.ttf"]},
            "death_counter": {"template": "Mortes: {n}", "position": "base_esquerda"},
        },
    }
).visual


def item(
    kind: EffectKind,
    start: int,
    frames: int,
    *,
    mode: EffectMode = EffectMode.RENDERIZADO,
    asset: str | None = None,
    params: dict[str, float | int | str] | None = None,
    item_id: str | None = None,
) -> FinishItem:
    track = {EffectKind.CONTADOR_MORTES: Track.V4, EffectKind.MUSICA: Track.A4}.get(kind, Track.A5)
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
        asset,
        params or {},
        "t",
    )


def test_drawtext_escape_and_colors() -> None:
    assert drawtext_escape("a:b'c%d\\e") == "a\\:b'\\\\\\''c\\%d\\\\e"
    assert ffmpeg_color("#ff0080") == "0xFF0080"
    assert ffmpeg_color("#000000", 0.65) == "0x000000@0.65"
    with pytest.raises(ValueError):
        ffmpeg_color("vermelho")


def test_counter_text_and_positions() -> None:
    assert counter_text(VISUAL.death_counter, 7) == "Mortes: 7"
    assert counter_position("topo_esquerda") == ("104", "104")
    assert counter_position("base_direita") == ("w-text_w-104", "h-text_h-104")


def test_counter_filter_is_transparent_rgba_with_alpha_fades() -> None:
    f = counter_filter("Mortes: 3", 180, VISUAL, "base_esquerda", Path("C:/fonts/T.ttf"))
    assert f.startswith("color=c=black@0.0:s=1920x1080:r=60:d=3.000000,format=rgba,drawtext=")
    assert "fontfile='C\\:/fonts/T.ttf'" in f and "text='Mortes\\: 3'" in f
    assert "fontcolor=0xFFEEDD" in f and "boxcolor=0x101010@0.65" in f
    assert "x=104:y=h-text_h-104" in f
    assert f.endswith("fade=t=out:st=2.800:d=0.200:alpha=1,format=yuva444p10le")
    with pytest.raises(ValueError):
        counter_filter("x", 1, VISUAL, "topo_direita", Path("f.ttf"))


def test_find_font_prefers_brand_file_then_system(tmp_path: Path) -> None:
    system = tmp_path / "sys.ttf"
    assert find_font(tmp_path, VISUAL, [str(system)]) is None
    system.write_bytes(b"x")
    assert find_font(tmp_path, VISUAL, [str(system)]) == system
    (tmp_path / "fonts").mkdir()
    (tmp_path / "fonts" / "T.ttf").write_bytes(b"x")
    assert find_font(tmp_path, VISUAL, [str(system)]) == tmp_path / "fonts" / "T.ttf"


def test_render_overlays_only_rendered_counters_and_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake(_s: Settings, args: list[str]) -> None:
        calls.append(args)
        Path(args[-1]).write_bytes(b"mov")

    monkeypatch.setattr("cronista.finishing.render.overlay.run_ffmpeg", fake)
    font = tmp_path / "f.ttf"
    font.write_bytes(b"x")
    finish = FinishPlan(
        items=[
            item(EffectKind.CONTADOR_MORTES, 100, 180, params={"ordem": 2}, item_id="c2"),
            item(
                EffectKind.CONTADOR_MORTES,
                900,
                180,
                mode=EffectMode.EDITAVEL,
                params={"ordem": 3},
                item_id="c3",
            ),
            item(EffectKind.SFX, 50, 0, asset="x", item_id="s"),
        ]
    )
    settings = Settings(env="test", data_dir=tmp_path)
    args = (finish, VISUAL, None, tmp_path / "ov", settings, None, [str(font)])
    first = render_overlays(*args)
    again = render_overlays(*args)
    assert list(first.clips) == ["c2"] and first.clips == again.clips and first.warnings == []
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[cmd.index("-frames:v") + 1] == "180" and "prores_ks" in cmd
    assert first.clips["c2"].name == overlay_name(finish.items[0], cmd[cmd.index("-i") + 1])


def test_render_overlays_warns_without_font(tmp_path: Path) -> None:
    finish = FinishPlan(items=[item(EffectKind.CONTADOR_MORTES, 0, 180, params={"ordem": 1})])
    result = render_overlays(
        finish, VISUAL, None, tmp_path, Settings(env="test", data_dir=tmp_path), None, []
    )
    assert result.clips == {} and "nenhuma fonte" in result.warnings[0]


def test_audio_frames_rounds_down(tmp_path: Path) -> None:
    path = tmp_path / "a.wav"
    soundfile.write(str(path), np.zeros(48000 * 2, dtype="float32"), 48000)
    assert audio_frames(path) == 120
    soundfile.write(str(path), np.zeros(int(48000 * 1.01), dtype="float32"), 48000)
    assert audio_frames(path) == 60  # 1,01 s = 60,6 quadros


def test_music_filtergraph_cuts_fades_delays_and_ducks() -> None:
    g = music_filtergraph([MusicClip(Path("a.wav"), 600, 1200), MusicClip(Path("b.wav"), 3000, 600)], 6000)
    assert "[0:a]aresample=48000" in g and "[1:a]aresample=48000" in g
    assert "atrim=duration=20.000000" in g and "afade=t=out:st=18.500:d=1.500" in g
    assert "volume=-20dB,adelay=10000|10000[m0]" in g and "adelay=50000|50000[m1]" in g
    assert "[m0][m1]amix=inputs=2:normalize=0:duration=longest[bed]" in g
    assert "[2:a]aresample=48000,aformat=channel_layouts=stereo[voice]" in g
    assert "[bed][voice]sidechaincompress=" in g
    assert g.endswith("[ducked]apad=whole_dur=100.000000,atrim=duration=100.000000[out]")


def test_music_filtergraph_single_clip_and_short_fades() -> None:
    g = music_filtergraph([MusicClip(Path("a.wav"), 0, 60)], 600)
    assert "[m0]anull[bed]" in g and "[1:a]" in g
    assert "afade=t=in:st=0:d=0.250" in g  # 1 s: fade limitado a 1/4 da duração
    with pytest.raises(ValueError):
        music_filtergraph([], 600)


def test_render_music_stem_runs_ffmpeg_with_all_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr("cronista.finishing.render.audio.run_ffmpeg", lambda _s, args: calls.append(args))
    song, voice = tmp_path / "song.wav", tmp_path / "A2.wav"
    song.write_bytes(b"x")
    voice.write_bytes(b"x")
    finish = FinishPlan(
        items=[
            item(EffectKind.MUSICA, 60, 1200, asset="m1", item_id="musica-1"),
            item(EffectKind.MUSICA, 2000, 600, mode=EffectMode.EDITAVEL, asset="m1", item_id="musica-2"),
            item(EffectKind.MUSICA, 3000, 600, asset="falta", item_id="musica-3"),
        ]
    )
    settings = Settings(env="test", data_dir=tmp_path)
    out, warnings = render_music_stem(finish, {"m1": song}, voice, tmp_path / "A4.wav", 6000, settings)
    assert out == tmp_path / "A4.wav" and len(calls) == 1
    assert [i.id for i in music_items(finish)] == ["musica-1", "musica-3"]
    assert calls[0].count("-i") == 2 and "[out]" in calls[0]
    assert any("musica-3" in w and "não encontrado" in w for w in warnings)


def test_render_music_stem_needs_voice_stem(tmp_path: Path) -> None:
    song = tmp_path / "song.wav"
    song.write_bytes(b"x")
    finish = FinishPlan(items=[item(EffectKind.MUSICA, 0, 1200, asset="m1")])
    settings = Settings(env="test", data_dir=tmp_path)
    out, warnings = render_music_stem(
        finish, {"m1": song}, tmp_path / "falta.wav", tmp_path / "A4.wav", 6000, settings
    )
    assert out is None and "stem de voz" in warnings[0]

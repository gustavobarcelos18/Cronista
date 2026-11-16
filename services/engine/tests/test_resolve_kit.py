from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

import pytest

from cronista.config import Settings
from cronista.devtools.resolve_kit import RECURSOS, make_media, make_resolve_kit

FPS = 60


@pytest.fixture
def kit_text(tmp_path: Path, settings: Settings) -> dict[str, Path]:
    return make_resolve_kit(settings, tmp_path / "kit", with_media=False)


def _times(root: ET.Element) -> list[tuple[str, str]]:
    return [
        (e.tag, e.get(a, ""))
        for e in root.iter()
        for a in ("offset", "start", "duration", "time")
        if e.get(a)
    ]


FCPXMLS = ["01-basico.fcpxml", *[f"{n}.fcpxml" for n in RECURSOS], "03-audio.fcpxml"]


@pytest.mark.parametrize("name", FCPXMLS)
def test_fcpxml_valido_e_na_grade_de_60_quadros(kit_text: dict[str, Path], name: str) -> None:
    root = ET.fromstring(kit_text[name].read_text(encoding="utf-8"))
    assert root.tag == "fcpxml"
    ids = {e.get("id") for e in root.find("resources") or []}
    refs = {e.get("ref") for e in root.iter() if e.get("ref") and e.tag != "text-style"}
    assert refs <= ids, f"refs sem recurso: {refs - ids}"
    for tag, raw in _times(root):
        if raw == "0s":
            continue
        assert raw.endswith("/60s"), f"<{tag}> fora do formato N/60s: {raw}"
        assert (Fraction(raw[:-1]) * FPS).denominator == 1
    fmt = root.find("resources/format")
    assert fmt is not None and fmt.get("frameDuration") == "1/60s"


def test_sequencia_dura_o_que_os_clipes_somam(kit_text: dict[str, Path]) -> None:
    root = ET.fromstring(kit_text["01-basico.fcpxml"].read_text(encoding="utf-8"))
    sequence = root.find(".//sequence")
    assert sequence is not None
    spine = sequence.find("spine")
    assert spine is not None
    total = sum(Fraction(c.get("duration", "0s")[:-1]) for c in spine)
    assert Fraction(sequence.get("duration", "0s")[:-1]) == total


def test_recursos_cobrem_o_checklist(kit_text: dict[str, Path]) -> None:
    esperado = {
        "02a-titulo": "<title",
        "02b-velocidade": "<timeMap>",
        "02c-zoom-keyframes": "keyframeAnimation",
        "02d-transicao": "<transition",
        "02e-overlay-alfa": 'lane="2"',
        "02f-hevc": "C_hevc",
    }
    assert set(esperado) == set(RECURSOS)
    for name, needle in esperado.items():
        assert needle in kit_text[f"{name}.fcpxml"].read_text(encoding="utf-8")
    audio = kit_text["03-audio.fcpxml"].read_text(encoding="utf-8")
    assert 'enabled="0"' in audio and audio.count("audio-channel-source") == 3


def test_edl_srt_e_lut(kit_text: dict[str, Path]) -> None:
    edl = kit_text["marcadores.edl"].read_text(encoding="utf-8")
    assert "|C:ResolveColorBlue |M:Momento |D:1" in edl and edl.count("|C:") == 3
    srt = kit_text["roteiro.srt"].read_text(encoding="utf-8")
    assert "00:00:01,000 --> 00:00:02,000" in srt
    cube = kit_text["teste.cube"].read_text(encoding="utf-8").splitlines()
    assert cube[1] == "LUT_3D_SIZE 17" and len(cube) == 2 + 17**3


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem FFmpeg")
def test_midia_do_kit(tmp_path: Path, settings: Settings) -> None:
    files = make_media(settings, tmp_path)
    assert {"A_h264", "B_h264", "overlay_alfa"} <= set(files)
    probe = subprocess.run(
        [settings.ffprobe, "-v", "error", "-show_entries", "stream=codec_name,pix_fmt,r_frame_rate",
         "-of", "csv=p=0", str(files["A_h264"])],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    lines = probe.stdout.split()
    assert "h264,yuv420p,60/1" in lines and sum(ln.startswith("aac") for ln in lines) == 3
    alpha = subprocess.run(
        [settings.ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=pix_fmt",
         "-of", "csv=p=0", str(files["overlay_alfa"])],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert "a" in alpha.stdout.strip()  # yuva444p10le: tem canal alfa
    # O retângulo precisa existir de fato: sem `replace=1` no drawbox o alfa não é escrito.
    graph = "[0][1]overlay=shortest=1,format=rgb24,crop=1:1:300:200"
    cmd = [settings.ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=black:s=1920x1080:d=1"]
    cmd += [
        "-i",
        str(files["overlay_alfa"]),
        "-filter_complex",
        graph,
        "-frames:v",
        "1",
        "-f",
        "rawvideo",
        "-",
    ]
    px = subprocess.run(cmd, capture_output=True, check=True)
    assert px.stdout[0] > 150 and px.stdout[1] < 40  # vermelho dentro do retângulo

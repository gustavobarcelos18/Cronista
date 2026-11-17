from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from cronista.assembly.plan import BrollClip, EditPlan, Mode, build_edit_plan
from cronista.config import Settings
from cronista.domain.frames import FPS
from cronista.export.montagem import (
    ExportMedia,
    MarkerInput,
    MediaFileInfo,
    check_plan_fcpxml,
    marker_lua,
    render_plan_fcpxml,
    render_timeline_srt,
    timeline_markers,
)
from cronista.export.pacote import next_version_dir
from cronista.export.timelapse import render_timelapses
from cronista.relevance.engine import Segment
from cronista.story.arc import BeatedSegment, Chapter
from cronista.story.models import Beat, ScriptLine, Span
from tests.conftest import needs_ffmpeg


def _seg(a: int, b: int, classe: str = "jogo", beat: Beat = Beat.CONFLITO) -> BeatedSegment:
    return BeatedSegment(Span(file_id=1, start_s=a, end_s=b), Segment(a, b, classe, 0.6, ["razão"]), beat)


def _plan() -> EditPlan:
    chapters = [Chapter(1, [_seg(100, 130), _seg(300, 700, "farm"), _seg(900, 930)], 600.0)]
    broll = {1: [BrollClip(1, 20 * FPS, 28 * FPS, 0.8, ("floresta",))]}
    return build_edit_plan(chapters, broll=broll, durations={1: 2000 * FPS})


def _media(tmp_path: Path, plan: EditPlan) -> ExportMedia:
    def touch(name: str) -> Path:
        path = tmp_path / name
        path.write_bytes(b"x")
        return path

    timelapses = {n: touch(f"tl{n}.mp4") for n, i in enumerate(plan.items) if i.mode == Mode.TIMELAPSE}
    stems = {k: touch(f"{k}.wav") for k in ("A1", "A2", "A6", "A7")}
    return ExportMedia(
        {1: MediaFileInfo(touch("master.mp4"), 2000 * FPS)}, timelapses, stems, plan.total_frames
    )


def test_fcpxml_multitrilha_passa_na_validacao(tmp_path: Path) -> None:
    plan = _plan()
    xml = render_plan_fcpxml(plan, _media(tmp_path, plan), "teste")
    assert check_plan_fcpxml(xml, plan) == []
    root = ET.fromstring(xml)
    spine = root.find("library/event/project/sequence/spine")
    assert spine is not None
    assert len(list(spine)) == len(plan.v1)
    lanes = {c.get("lane") for c in spine.iter("asset-clip") if c.get("lane")}
    assert lanes == {"-1", "-2", "-6", "-7", "2"}
    assert len(list(spine.iter("title"))) == 1  # a cartela do capítulo
    disabled = [e for e in spine.iter("audio-channel-source") if e.get("enabled") == "0"]
    assert len(disabled) == 2 * len(plan.v1)  # A6 e A7 em cada corte


def test_timelapse_aponta_para_o_arquivo_renderizado(tmp_path: Path) -> None:
    plan = _plan()
    xml = render_plan_fcpxml(plan, _media(tmp_path, plan), "teste")
    root = ET.fromstring(xml)
    names = {c.get("name"): c for c in root.iter("asset-clip")}
    farm = names["timelapse|1:300"]
    assert farm.get("start") == "0/60s"
    asset = next(a for a in root.iter("asset") if a.get("id") == farm.get("ref"))
    assert asset.get("name").startswith("tl")  # type: ignore[union-attr]


def test_validacao_pega_arquivo_inexistente_e_clipe_alem_do_fim(tmp_path: Path) -> None:
    plan = _plan()
    media = _media(tmp_path, plan)
    (tmp_path / "A1.wav").unlink()
    problems = check_plan_fcpxml(render_plan_fcpxml(plan, media), plan)
    assert any("A1.wav" in p and "não existe" in p for p in problems)
    short = ExportMedia(
        {1: MediaFileInfo(media.masters[1].path, 10 * FPS)}, media.timelapses, media.stems, 100
    )
    problems = check_plan_fcpxml(render_plan_fcpxml(plan, short), plan)
    assert any("passa do fim" in p for p in problems)


def test_srt_em_tempo_de_timeline_com_fala_vazia_em_zero() -> None:
    plan = _plan()
    item = plan.v1[0]
    lines = [
        ScriptLine(segment_id="1:100", text="Primeira.", est_s=2.0, start_s=101.5),
        ScriptLine(
            segment_id="1:900", text="Antes da hora.", kind="antecipacao", est_s=1.0, justification="x"
        ),
        ScriptLine(segment_id="9:9", text="Sem trecho.", est_s=1.0),
    ]
    srt = render_timeline_srt(plan, lines)
    blocks = srt.strip().split("\n\n")
    assert blocks[0].splitlines()[1:] == ["00:00:00,000 --> 00:00:01,000", "."]
    assert len(blocks) == 3  # a linha de segmento fora da montagem some
    start = item.timeline_start + 101 * FPS + FPS // 2 - item.in_frame
    assert f"{start // FPS // 60:02}:{start // FPS % 60:02}" in blocks[1].splitlines()[1]
    assert "[ANTECIPAÇÃO] Antes da hora." in blocks[2]


def test_marcadores_na_timeline_e_lua_de_uma_linha() -> None:
    plan = _plan()
    first = plan.v1[0]
    marks = [
        MarkerInput(1, first.in_frame + 90, "conquista", 'm "1"'),
        MarkerInput(1, 50 * FPS, "momento", "fora"),  # antes de qualquer trecho usado
    ]
    result, skipped = timeline_markers(plan, marks)
    assert len(result) == 1 and result[0].frame == first.timeline_start + 90
    assert result[0].color == "Green" and "conquista|m" in result[0].note
    assert skipped and "fora dos trechos" in skipped[0]
    (line,) = marker_lua(result)
    assert "\n" not in line and line.startswith("local t = resolve:")
    assert '\\"1\\"' in line  # aspas escapadas


def test_lua_parte_em_varias_linhas_quando_passa_do_limite() -> None:
    plan = _plan()
    first = plan.v1[0]
    marks = [MarkerInput(1, first.in_frame + n, "momento", f"id{n}") for n in range(20)]
    result, _ = timeline_markers(plan, marks)
    chunks = marker_lua(result, max_chars=900)
    assert len(chunks) > 1
    assert all(len(c) <= 900 + 400 for c in chunks)
    assert sum(c.count("m(") - 1 for c in chunks) == 20  # `m(` da definição não conta


def test_versoes_nunca_sobrescrevem(tmp_path: Path) -> None:
    first, v1 = next_version_dir(tmp_path)
    first.mkdir()
    second, v2 = next_version_dir(tmp_path)
    assert (v1, v2) == (1, 2) and first != second


@needs_ffmpeg
def test_timelapse_renderizado_tem_a_duracao_do_plano(tmp_path: Path, settings: Settings) -> None:
    master = tmp_path / "m.mp4"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=60", "-t", "30",
         "-pix_fmt", "yuv420p", str(master)],
        check=True,
    )  # fmt: skip
    chapters = [Chapter(1, [_seg(0, 30, "farm")], 600.0)]
    plan = build_edit_plan(chapters, durations={1: 30 * FPS})
    item = plan.v1[0]
    assert item.mode == Mode.TIMELAPSE
    done = render_timelapses(plan, {1: master}, tmp_path / "tl", settings)
    out = done[0]
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert int(probe.stdout.strip()) == item.timeline_frames
    assert render_timelapses(plan, {1: master}, tmp_path / "tl", settings)[0] == out  # reaproveita

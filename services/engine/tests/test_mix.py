from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from cronista.assembly.plan import EditPlan, build_edit_plan
from cronista.config import Settings
from cronista.domain.frames import FPS
from cronista.mix.envelope import (
    CONTROL_RATE,
    DuckParams,
    gain_at,
    gain_curve,
    merge_intervals,
    narration_intervals,
    timeline_intervals,
)
from cronista.mix.loudness import measure, parse_ebur128
from cronista.mix.service import mix_plan
from cronista.mix.stems import RATE, SAMPLES_PER_FRAME, render_stem
from cronista.relevance.engine import Segment
from cronista.story.arc import BeatedSegment, Chapter
from cronista.story.models import Beat, Script, ScriptLine, Span
from tests.conftest import needs_ffmpeg


def _plan(*spans: tuple[int, int, str]) -> EditPlan:
    items = [
        BeatedSegment(Span(file_id=1, start_s=a, end_s=b), Segment(a, b, classe, 0.6, ["x"]), Beat.CONFLITO)
        for a, b, classe in spans
    ]
    return build_edit_plan([Chapter(1, items, 600.0)])


def _tone(seconds: float, hz: float, amp: float = 0.3) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    mono = (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32)
    return np.stack([mono, mono], axis=1)


def _wav(path: Path, data: np.ndarray) -> Path:
    sf.write(str(path), data, RATE, subtype="PCM_16")
    return path


def test_envelope_abaixa_dentro_e_volta_fora() -> None:
    params = DuckParams(duck_db=-12.0, pad_s=0.0)
    curve = gain_curve(20 * FPS, [(5 * FPS, 10 * FPS)], params)
    low = 10 ** (-12 / 20)
    assert curve[2 * CONTROL_RATE] == 1.0
    assert abs(curve[int(9.9 * CONTROL_RATE)] - low) < 0.02  # ataque já terminou
    assert curve[int(10.1 * CONTROL_RATE)] < 0.6  # soltura ainda em rampa
    assert curve[19 * CONTROL_RATE] > 0.98
    assert float(curve.min()) >= low - 1e-6


def test_gain_at_interpola_sem_degraus() -> None:
    curve = gain_curve(10 * FPS, [(2 * FPS, 6 * FPS)], DuckParams())
    g = gain_at(curve, 0, RATE * 10, RATE)
    assert len(g) == RATE * 10
    assert float(np.abs(np.diff(g)).max()) < 0.01


def test_intervalos_para_a_timeline_e_timelapse_sem_audio() -> None:
    plan = _plan((100, 120, "jogo"), (300, 700, "farm"))
    first = plan.v1[0]
    ranges = {1: [(first.in_frame + 60, first.in_frame + 180), (300 * FPS, 400 * FPS)]}
    got = timeline_intervals(plan.items, ranges)
    assert got == [(first.timeline_start + 60, first.timeline_start + 180)]  # o do timelapse some


def test_narracao_usa_start_s_e_corta_no_fim_do_trecho() -> None:
    plan = _plan((100, 120, "jogo"))
    item = plan.v1[0]
    script = Script(
        lines=[ScriptLine(segment_id="1:100", text="uma fala qualquer", est_s=2.0, start_s=105.0)]
    )
    ((a, b),) = narration_intervals(plan.items, script.lines)
    assert a == item.timeline_start + 105 * FPS - item.in_frame
    assert b - a == 2 * FPS
    long = ScriptLine(segment_id="1:100", text="x", est_s=99.0, start_s=118.0)
    assert narration_intervals(plan.items, [long])[0][1] == item.timeline_end


def test_merge_intervals() -> None:
    assert merge_intervals([(5, 9), (0, 3), (2, 4)]) == [(0, 4), (5, 9)]


def test_parse_ebur128() -> None:
    text = "Summary:\n Integrated loudness:\n  I: -23.4 LUFS\n True peak:\n  Peak: -1.2 dBFS\n"
    got = parse_ebur128(text)
    assert got.lufs == -23.4 and got.true_peak_db == -1.2
    assert parse_ebur128("Summary:\n I: -70.0 LUFS\n Peak: -inf dBFS\n").lufs is None


def test_stem_tem_amostras_exatas_e_timelapse_mudo(tmp_path: Path) -> None:
    plan = _plan((10, 20, "jogo"), (100, 400, "farm"))
    game = _wav(tmp_path / "g.wav", _tone(500.0, 440.0))
    out = tmp_path / "stem.wav"
    total = render_stem(plan.items, {1: game}, out)
    assert total == plan.total_frames * SAMPLES_PER_FRAME
    data, rate = sf.read(str(out), dtype="float32")
    assert rate == RATE and len(data) == total
    first = plan.v1[0].timeline_frames * SAMPLES_PER_FRAME
    assert float(np.abs(data[:first]).max()) > 0.2
    assert float(np.abs(data[first:]).max()) == 0.0


@needs_ffmpeg
def test_mixagem_completa_niveis_ducking_e_crus(tmp_path: Path, settings: Settings) -> None:
    plan = _plan((10, 40, "jogo"))
    item = plan.v1[0]
    game = _wav(tmp_path / "g.wav", _tone(60.0, 440.0, 0.4))
    mic = _wav(tmp_path / "m.wav", _tone(60.0, 880.0, 0.2))
    # voz ao vivo nos 10 s do meio do trecho
    mid = item.in_frame + 10 * FPS
    speech = {1: [(mid, mid + 10 * FPS)]}
    report = mix_plan(plan, {1: game}, {1: mic}, speech, None, settings, tmp_path / "stems")

    names = {s.name: s for s in report.stems}
    assert set(names) == {"A1-jogo.wav", "A2-voz.wav", "A6-jogo-cru.wav", "A7-microfone-cru.wav"}
    assert names["A2-voz.wav"].lufs is not None and abs(names["A2-voz.wav"].lufs - (-16.0)) < 1.5
    assert names["A1-jogo.wav"].lufs is not None and abs(names["A1-jogo.wav"].lufs - (-24.0)) < 1.5
    for s in report.stems:
        assert s.true_peak_db is not None and s.true_peak_db <= 0.0
    assert report.ducked_s > 9.0
    assert not (tmp_path / "stems" / "_tmp").exists()

    a1, _ = sf.read(str(tmp_path / "stems" / "A1-jogo.wav"), dtype="float32")
    a6, _ = sf.read(str(tmp_path / "stems" / "A6-jogo-cru.wav"), dtype="float32")
    assert len(a1) == len(a6) == plan.total_frames * SAMPLES_PER_FRAME
    inside = slice(int(15 * RATE), int(18 * RATE))
    outside = slice(int(2 * RATE), int(5 * RATE))

    def rms(x: np.ndarray, s: slice) -> float:
        return float(np.sqrt(np.mean(x[s] ** 2)))

    ratio = (rms(a1, inside) / rms(a1, outside)) / (rms(a6, inside) / rms(a6, outside))
    assert 0.2 < ratio < 0.35  # -12 dB = 0,25
    assert measure(settings, tmp_path / "stems" / "A1-jogo.wav").lufs is not None

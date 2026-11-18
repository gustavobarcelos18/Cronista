from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from cronista.audio.scream import ScreamHeuristic

RATE = 16000


def _tone(freq: float, seconds: float, amp: float) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    # fundamental + harmônicos, como uma voz
    wave = np.sum([np.sin(2 * np.pi * freq * k * t) / k for k in (1, 2, 3)], axis=0)
    return (amp * wave / 1.8).astype(np.float32)


def _wav(tmp_path: Path, parts: list[np.ndarray]) -> Path:
    path = tmp_path / "mic.wav"
    sf.write(str(path), np.concatenate(parts), RATE)
    return path


def test_grito_agudo_e_alto_e_detectado_fala_normal_nao(tmp_path: Path) -> None:
    silence = np.zeros(RATE, dtype=np.float32)
    speech = _tone(130, 20, 0.06)  # fala normal: grave e média
    shout = _tone(380, 1.0, 0.5)  # grito: agudo e bem mais forte
    path = _wav(tmp_path, [silence, speech, shout, speech, silence])
    spans = ScreamHeuristic().classify(path, pause=lambda: None)
    assert len(spans) == 1
    assert spans[0].label == "exclamacao"
    assert 20.5 < spans[0].start_s < 21.5


def test_fala_alta_mas_grave_nao_vira_grito(tmp_path: Path) -> None:
    speech = _tone(130, 20, 0.06)
    loud_low = _tone(150, 1.0, 0.5)  # alto, mas sem subir o tom
    path = _wav(tmp_path, [speech, loud_low, speech])
    assert ScreamHeuristic().classify(path, pause=lambda: None) == []


def test_arquivo_mudo_nao_gera_evento(tmp_path: Path) -> None:
    path = _wav(tmp_path, [np.zeros(RATE * 5, dtype=np.float32)])
    assert ScreamHeuristic().classify(path, pause=lambda: None) == []


def test_a12_time_uses_the_real_hop_not_the_nominal_frame() -> None:
    import numpy as np

    from cronista.audio.scream import ScreamParams, find_screams

    p = ScreamParams()
    level = np.full(40_000, -30.0, dtype=np.float32)
    level[39_000:39_020] = 0.0
    f0 = np.full(40_000, 400.0, dtype=np.float32)
    hop_s = int(p.frame_s * 22050) / 22050  # 551 amostras: 0,024989 s, não 0,025
    (span,) = find_screams(level, f0, p, hop_s=hop_s)
    assert span[0] == 39_000 * hop_s and 39_000 * hop_s < 39_000 * p.frame_s - 0.4

from __future__ import annotations

import pytest

from cronista.audio.quality import (
    Utterance,
    evaluate,
    false_events_per_10_min,
    match_events,
    normalize_text,
    routine_recall,
    wer,
)
from cronista.gabarito import Annotation


def test_normaliza_acento_e_pontuacao() -> None:
    assert normalize_text("Olá, Mundo! É 1.") == ["ola", "mundo", "e", "1"]


@pytest.mark.parametrize(
    ("ref", "hyp", "expected"),
    [("a b c d", "a b c d", 0.0), ("a b c d", "a x c", 0.5), ("a b", "", 1.0), ("", "a", None)],
)
def test_wer(ref: str, hyp: str, expected: float | None) -> None:
    assert wer(ref, hyp) == expected


def test_match_events_com_tolerancia() -> None:
    det = match_events([(600, 660)], [(690, 720), (5000, 5100)], tolerance_frames=60)
    assert (det.true_positives, det.predicted, det.expected) == (1, 2, 1)
    assert det.precision == 0.5 and det.recall == 1.0


def test_falsos_por_10_min() -> None:
    # 1 falso em 5 min = 2 a cada 10 min
    assert false_events_per_10_min([(0, 100)], [(10, 20), (500, 600)], 5 * 60 * 60) == pytest.approx(2.0)


def test_rotina_cobertura() -> None:
    assert routine_recall([(0, 100), (500, 600)], [(0, 80)]) == 0.5
    assert routine_recall([], [(0, 80)]) is None


def test_evaluate_completo() -> None:
    anns = [
        Annotation(2, 0, 600, "fala", "olá mundo"),
        Annotation(3, 1200, 1260, "risada", ""),
        Annotation(4, 2000, 2100, "teclado", ""),
    ]
    rep = evaluate(
        anns,
        [Utterance(10, 500, "Olá mundo")],
        [("risada", (1210, 1250)), ("grito", (2050, 2060))],
        [],
        total_frames=60 * 600,
    )
    assert rep.wer == 0.0
    assert rep.detection["risada"].recall == 1.0
    assert rep.false_per_10_min["teclado"] == pytest.approx(1.0)


def test_texto_do_whisper_sobre_respiracao_conta_como_falso() -> None:
    anns = [Annotation(2, 100, 200, "respiracao", ""), Annotation(3, 1000, 1200, "fala", "oi")]
    rep = evaluate(
        anns,
        [Utterance(110, 190, "a suar o nariz"), Utterance(1000, 1200, "oi")],
        [],
        [],
        total_frames=60 * 300,
    )
    assert rep.false_per_10_min["respiracao"] == pytest.approx(2.0)
    assert rep.wer == 0.0

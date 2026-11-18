"""Painel da série (B9, B11, B12): situação por projeto e `curto_ok` quando o arco está completo."""

from __future__ import annotations

from cronista.relevance.engine import Segment
from cronista.review.panel import situation
from cronista.story.arc import arc_complete, assign_beats, build_chapters


def _chapters(segs: list[Segment], kinds: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
    return build_chapters([(1, segs)], kinds or {})


def test_situacao_abaixo_de_30_min_depende_do_arco() -> None:
    assert situation(25.0, True) == "curto_ok"
    assert situation(25.0, False) == "abaixo_da_referencia"
    assert situation(40.0, False) == "no_alvo"
    assert situation(55.0, True) == "acima"


def test_arco_completo_precisa_de_comeco_meio_e_climax() -> None:
    kinds = {"f": "morte_falha", "c": "conquista"}
    segs = [
        Segment(0, 30, "jogo", 0.6),
        Segment(30, 60, "momento", 0.8, markers=["f"]),
        Segment(60, 90, "momento", 0.9, markers=["c"]),
    ]
    chapters = _chapters(segs, kinds)
    assert arc_complete(chapters)
    only_start = _chapters(segs[:1], kinds)
    assert not arc_complete(only_start)
    assert not arc_complete([])
    assign_beats(only_start[0])  # idempotente

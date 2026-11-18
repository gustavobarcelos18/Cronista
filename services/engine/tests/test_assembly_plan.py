from __future__ import annotations

import itertools
import json

from cronista.assembly.plan import (
    AssemblyParams,
    BrollClip,
    Mode,
    Track,
    WordSpan,
    build_edit_plan,
    snap_out_of_words,
)
from cronista.domain.frames import FPS
from cronista.relevance.engine import Segment
from cronista.story.arc import BeatedSegment, Chapter
from cronista.story.models import Beat, Span


def _seg(
    start: int,
    end: int,
    *,
    classe: str = "jogo",
    score: float = 0.5,
    beat: Beat = Beat.CONFLITO,
    markers: list[str] | None = None,
    file_id: int = 1,
) -> BeatedSegment:
    segment = Segment(start, end, classe, score, ["razão"], markers or [])
    return BeatedSegment(Span(file_id=file_id, start_s=start, end_s=end), segment, beat)


def _chapter(items: list[BeatedSegment], allocated: float = 600.0, number: int = 1) -> Chapter:
    return Chapter(number=number, items=items, allocated_s=allocated)


def test_cortes_em_quadros_inteiros_com_folga() -> None:
    plan = build_edit_plan([_chapter([_seg(100, 120)])])
    item = plan.v1[0]
    assert item.in_frame == (100 - 1.5) * FPS
    assert item.out_frame == (120 + 1.5) * FPS
    assert isinstance(item.in_frame, int) and isinstance(item.timeline_frames, int)
    assert plan.total_frames == item.timeline_frames


def test_corte_nao_fica_dentro_de_palavra() -> None:
    # início com folga cairia em 98,5 s, no meio da palavra que vai de 98 s a 99 s
    words = [WordSpan(98 * FPS, 99 * FPS)]
    plan = build_edit_plan([_chapter([_seg(100, 120)])], words={1: words})
    assert plan.v1[0].in_frame == 98 * FPS
    assert snap_out_of_words(int(98.5 * FPS), words, 10, move_to="start") == int(
        98.5 * FPS
    )  # limite curto: fica


def test_farm_vira_timelapse_e_resumo_mantem_o_desfecho() -> None:
    plan = build_edit_plan([_chapter([_seg(0, 400, classe="farm", score=0.1), _seg(500, 600, score=0.9)])])
    farm, long_ = plan.v1
    assert farm.mode == Mode.TIMELAPSE and farm.speed == 20
    assert farm.timeline_frames == round(400 * FPS / 20)
    assert long_.mode == Mode.MONTAGEM
    assert long_.out_frame == int(601.5 * FPS)
    assert long_.timeline_frames == 45 * FPS


def test_orcamento_tira_menor_nota_e_poupa_protegidos() -> None:
    items = [
        _seg(0, 40, score=0.4),
        _seg(100, 140, score=0.3),
        _seg(200, 240, score=0.2, beat=Beat.CONQUISTA, markers=["m1"]),
    ]
    plan = build_edit_plan([_chapter(items, allocated=90)])
    ids = [i.segment_id for i in plan.v1]
    assert ids == ["1:0", "1:200"]  # saiu o de nota 0,3; o de nota 0,2 é conquista, fica
    assert plan.chapter_s(1) <= 90 + 1e-9


def test_so_protegidos_acima_do_orcamento_avisa() -> None:
    items = [_seg(0, 40, beat=Beat.FALHA), _seg(100, 140, beat=Beat.CONQUISTA)]
    plan = build_edit_plan([_chapter(items, allocated=30)])
    assert len(plan.v1) == 2
    assert any("acima do orçamento" in w for w in plan.warnings)


def test_trechos_que_se_tocam_no_mesmo_arquivo_sao_fundidos() -> None:
    plan = build_edit_plan([_chapter([_seg(10, 20), _seg(21, 30)])])
    assert len(plan.v1) == 1
    assert plan.v1[0].in_frame == int(8.5 * FPS) and plan.v1[0].out_frame == int(31.5 * FPS)


def test_corte_fundido_guarda_os_ids_de_todos_os_trechos() -> None:
    """C2 (auditoria 10A): a fala do segundo trecho fundido não pode sumir do SRT e do ducking."""
    from cronista.mix.envelope import narration_cues
    from cronista.story.models import ScriptLine

    plan = build_edit_plan([_chapter([_seg(10, 20), _seg(21, 30)])])
    (item,) = plan.v1
    assert item.segment_ids == ("1:10", "1:21")
    line = ScriptLine(segment_id="1:21", text="Aqui eu voltei.", est_s=2.0, start_s=22.0)
    cues = narration_cues(plan.items, [line])
    assert len(cues) == 1 and cues[0][2] is line


def test_limite_do_arquivo_e_sequencia_sem_buracos() -> None:
    plan = build_edit_plan([_chapter([_seg(0, 10), _seg(100, 109)])], durations={1: 110 * FPS})
    first, second = plan.v1
    assert first.in_frame == 0
    assert second.out_frame == 110 * FPS
    assert second.timeline_start == first.timeline_end


def test_broll_em_v3_e_cartela_por_capitulo_sem_numero() -> None:
    broll = {1: [BrollClip(1, 5000 * FPS, 5010 * FPS, 0.9, ("floresta",)), BrollClip(1, 0, 10 * FPS, 0.99)]}
    chapters = [_chapter([_seg(100, 130)], number=1), _chapter([_seg(300, 330)], number=2)]
    plan = build_edit_plan(chapters, broll=broll, durations={1: 6000 * FPS})
    v3 = [i for i in plan.items if i.track == Track.V3]
    assert len(v3) == 2
    assert all(i.in_frame >= 0 and i.timeline_frames <= 6 * FPS for i in v3)
    assert [c.text for c in plan.cards] == ["Capítulo 1", "Capítulo 2"]
    assert all(c.editable_number and "Dia" not in c.text for c in plan.cards)
    assert plan.cards[1].timeline_start == plan.v1[1].timeline_start


def test_deterministico_e_json_valido() -> None:
    chapters = [_chapter([_seg(0, 40), _seg(100, 140, classe="farm")])]
    a = build_edit_plan(chapters, params=AssemblyParams())
    b = build_edit_plan(chapters, params=AssemblyParams())
    assert a.to_json() == b.to_json()
    assert json.loads(a.to_json())["fps"] == 60


def test_sem_sobreposicao_em_v1() -> None:
    items = [_seg(0, 30), _seg(25, 60, classe="farm", score=0.1), _seg(70, 100)]
    plan = build_edit_plan([_chapter(items)])
    v1 = plan.v1
    for a, b in itertools.pairwise(v1):
        assert b.timeline_start == a.timeline_end
        if a.file_id == b.file_id:
            assert b.in_frame >= a.out_frame

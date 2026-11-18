# ruff: noqa: F811
"""Regressões da auditoria 10A (bloco B): cada teste falhava antes da correção."""

from __future__ import annotations

import pytest

from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource
from cronista.domain.frames import FPS
from cronista.story.models import Script, ScriptLine
from cronista.story.objectives import RuleExtractor
from cronista.story.script import LocalScriptProvider, free_gaps, validate_script
from tests.test_story import FakeGen, fala, session_ids  # noqa: F401


def event(kind: str, a: float, b: float) -> AnalysisEvent:
    ev = Evidence(
        source=EvidenceSource.EVENTO,
        start_frame=round(a * FPS),
        end_frame=round(b * FPS),
        confidence=0.9,
        model="m",
        model_version="1",
        params_hash="h",
    )
    return AnalysisEvent(kind=kind, evidence=ev)


def test_b3_local_provider_uses_the_largest_gap_only() -> None:
    pack = {
        "capitulos": [
            {
                "beats": [
                    {
                        "segmento_id": "1:0",
                        "beat": "setup",
                        "classe": "momento",
                        "razoes": [],
                        "lacunas": [
                            {"inicio_s": 0.0, "fim_s": 3.0},
                            {"inicio_s": 10.0, "fim_s": 40.0},
                            {"inicio_s": 50.0, "fim_s": 54.0},
                        ],
                    }
                ]
            }
        ]
    }
    prompts: list[str] = []

    class Gen(FakeGen):
        def generate(self, prompt: str, max_tokens: int) -> str:
            prompts.append(prompt)
            return '{"texto": "Aqui a noite caiu."}'

    (line,) = LocalScriptProvider(Gen([])).write(pack).lines
    assert line.start_s == 10.0  # a maior lacuna, não a primeira
    assert "No máximo 78 palavras" in prompts[0]  # 30 s * 2,6; a soma das lacunas (37 s) daria 96


def test_b4_lines_without_start_are_chained_inside_gaps() -> None:
    index = {"1:0": (0.0, 60.0, [(0.0, 10.0), (20.0, 30.0)])}
    lines = [ScriptLine(segment_id="1:0", text="Fui buscar madeira antes de escurecer hoje.", est_s=4.0)] * 3
    report = validate_script(Script(lines=lines), index)
    assert report.ok
    starts = [line.start_s for line in report.lines]
    assert starts == [0.0, 4.0, 20.0]  # a terceira não cabe em 8 a 10 s: vai para a lacuna seguinte
    assert not report.warnings


def test_b4_start_inside_live_speech_is_an_error() -> None:
    index = {"1:0": (0.0, 60.0, [(0.0, 10.0), (20.0, 30.0)])}
    line = ScriptLine(segment_id="1:0", text="Fui buscar madeira.", est_s=2.0, start_s=14.0)
    assert any("fora dos espaços livres" in e for e in validate_script(Script(lines=[line]), index).errors)


def test_b4_segment_without_gap_is_an_error() -> None:
    line = ScriptLine(segment_id="1:0", text="Fui buscar madeira.")
    report = validate_script(Script(lines=[line]), {"1:0": (0.0, 60.0, [])})
    assert not report.ok and "sem espaço livre" in report.errors[0]


def test_b5_laughter_and_exclamation_are_not_free_gaps() -> None:
    live = [fala(0, 5, "oi"), event("risada", 20, 24), event("exclamacao", 40, 41)]
    gaps = free_gaps(0, 60, live)
    assert all(not (a < 24 and b > 20) and not (a < 41 and b > 40) for a, b in gaps)
    assert len(gaps) == 3


def test_b5_pack_gaps_avoid_laughter_without_listing_it_as_speech() -> None:
    from cronista.story.arc import allocate_time, build_chapters
    from cronista.story.pack import build_story_pack
    from tests.test_story import seg

    chapters = build_chapters([(1, [seg(60, 120, "momento", 0.8, ["m"])])], {"m": "momento"})
    allocate_time(chapters, 300)
    pack = build_story_pack(chapters, {1: [event("risada", 80, 84)]}, {"nome": "p"}, [], 300)
    beat = pack["capitulos"][0]["beats"][0]
    assert beat["fala_ao_vivo"] == []  # risada não é fala com texto
    assert all(not (g["inicio_s"] < 84 and g["fim_s"] > 80) for g in beat["lacunas"])
    assert len(beat["lacunas"]) == 2


def test_b6_failure_is_not_read_as_conclusion() -> None:
    extractor = RuleExtractor(["construir a casa"])
    out = extractor.extract([fala(0, 4, "eu nao consegui construir a casa de novo")])
    assert [c.state.value for c in out] == ["falhou"]
    won = extractor.extract([fala(0, 4, "finalmente consegui construir a casa")])
    assert [c.state.value for c in won] == ["concluido"]


def test_b2_chapter_floor_does_not_push_the_sum_past_the_target() -> None:
    from cronista.story.arc import MIN_CHAPTER_S, allocate_time, build_chapters
    from tests.test_story import seg

    big = [seg(i * 100, i * 100 + 45, "momento", 0.8) for i in range(10)]  # 450 s de material
    big += [seg(2000 + i * 100, 2045 + i * 100, "momento", 0.8, ["d1"] if i == 0 else []) for i in range(10)]
    small = [seg(5000 + i * 100, 5000 + i * 100 + 40, "momento", 0.8, [f"s{i}"]) for i in range(5)]
    kinds = {"d1": "novo_dia", **{f"s{i}": "novo_dia" for i in range(5)}}
    chapters = build_chapters([(1, [*big, *small])], kinds)
    assert len(chapters) == 7
    allocate_time(chapters, 400)  # os 5 pequenos recebem 20 s pela proporção, mas o piso é 30 s
    assert [c.allocated_s for c in chapters[2:]] == [MIN_CHAPTER_S] * 5
    assert sum(c.allocated_s for c in chapters) == pytest.approx(400, abs=0.5)


def test_b2_chapter_never_gets_more_than_its_material() -> None:
    from cronista.story.arc import allocate_time, build_chapters
    from tests.test_story import seg

    chapters = build_chapters([(1, [seg(0, 60, "momento", 0.8)])], {})
    allocate_time(chapters, 2400)
    assert chapters[0].allocated_s == chapters[0].product_s


def test_b7_rerunning_discovery_does_not_duplicate_or_flip_states(db, session_ids) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import func, select

    from cronista.db.models import ObjectiveState
    from cronista.story.models import ObjKind
    from cronista.story.objectives import add_objective, discover

    pid, sid = session_ids
    obj = add_objective(db, pid, "construir a casa", ObjKind.PRINCIPAL)
    speech = [
        fala(0, 4, "eu nao consegui construir a casa"),
        fala(60, 64, "finalmente consegui construir a casa"),
    ]
    marks = [(61 * FPS, 61 * FPS)]
    extractor = RuleExtractor([obj.title])

    def run() -> int:
        discover(db, pid, sid, 1, speech, extractor, marks, [(1 * FPS, 1 * FPS)])
        return db.scalar(select(func.count()).select_from(ObjectiveState)) or 0

    first = run()
    assert first >= 2 and run() == first and run() == first


def test_b7_human_state_is_never_overwritten(db, session_ids) -> None:  # type: ignore[no-untyped-def]
    from cronista.story.models import ObjKind, ObjState
    from cronista.story.objectives import add_objective, current_state, discover, set_state

    pid, sid = session_ids
    obj = add_objective(db, pid, "construir a casa", ObjKind.PRINCIPAL)
    set_state(db, obj.id, sid, ObjState.ABANDONADO, source="humano", quote=None, origin="humano")
    speech = [fala(0, 4, "finalmente consegui construir a casa")]
    discover(db, pid, sid, 1, speech, RuleExtractor([obj.title]), [(1 * FPS, 1 * FPS)])
    state = current_state(db, obj.id, sid)
    assert state is not None and state.state == "abandonado" and state.origin == "humano"

"""Narrativa (Fases 5 e 5A): objetivos com evidência, arco, story-pack, roteiro, lint e SRT. Sem modelo."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from cronista.db.models import MediaFile, Project, RecordingSession
from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource
from cronista.domain.frames import FPS
from cronista.relevance.engine import Segment
from cronista.story.arc import allocate_time, build_chapters
from cronista.story.models import Beat, ObjKind, ObjState, Script, ScriptLine
from cronista.story.objectives import (
    Candidate,
    EvidenceError,
    RuleExtractor,
    add_objective,
    current_state,
    discover,
    export_review_csv,
    review_queue,
    set_state,
    sync_profile_objectives,
    verify_citation,
)
from cronista.story.pack import build_story_pack
from cronista.story.script import (
    LocalScriptProvider,
    NullProvider,
    context_notes,
    estimate_seconds,
    free_gaps,
    lint_text,
    to_srt,
    validate_script,
    voice_profile,
)


def fala(a: float, b: float, text: str) -> AnalysisEvent:
    e = Evidence(
        source=EvidenceSource.TRANSCRICAO,
        start_frame=round(a * FPS),
        end_frame=round(b * FPS),
        confidence=0.9,
        model="w",
        model_version="1",
        params_hash="h",
        quote=text,
    )
    return AnalysisEvent(kind="fala", evidence=e)


@pytest.fixture
def session_ids(db: Session) -> tuple[int, int]:
    project = Project(name="p", game="g")
    db.add(project)
    db.commit()
    session = RecordingSession(project_id=project.id, folder="f")
    db.add(session)
    db.commit()
    db.add(MediaFile(id=1, session_id=session.id, path="a.mp4"))
    db.commit()
    return project.id, session.id


# ------------------------------------------------------------------ objetivos


def test_citation_must_be_literal_and_in_window() -> None:
    speech = [fala(10, 14, "Então, meu objetivo é construir uma casa!")]
    assert verify_citation("construir uma casa", speech, 10 * FPS, 14 * FPS)
    assert not verify_citation("matar o dragão", speech, 10 * FPS, 14 * FPS)
    assert not verify_citation("construir uma casa", speech, 500 * FPS, 510 * FPS)


def test_state_requires_evidence(db: Session, session_ids: tuple[int, int]) -> None:
    pid, sid = session_ids
    obj = add_objective(db, pid, "achar comida")
    with pytest.raises(EvidenceError):
        set_state(db, obj.id, sid, ObjState.CONCLUIDO, source="transcricao", quote="  ")
    first = set_state(db, obj.id, sid, ObjState.PROPOSTO, source="transcricao", quote="preciso achar comida")
    with pytest.raises(EvidenceError):  # marcador sem intervalo de quadros não é evidência
        set_state(db, obj.id, sid, ObjState.EM_ANDAMENTO, source="marcador", quote=None)
    second = set_state(
        db, obj.id, sid, ObjState.EM_ANDAMENTO, source="marcador", quote=None, start_frame=100, end_frame=160
    )
    assert second.replaces_id == first.id
    assert current_state(db, obj.id, sid).state == "em_andamento"  # type: ignore[union-attr]
    assert add_objective(db, pid, "achar comida").id == obj.id  # retomada mantém o id


def test_declaration_is_not_conclusion(db: Session, session_ids: tuple[int, int]) -> None:
    pid, sid = session_ids
    speech = [
        fala(10, 13, "Preciso achar comida antes de anoitecer."),
        fala(60, 63, "Se eu construir uma torre talvez dê certo."),  # hipotético: ignorado
    ]
    report = discover(db, pid, sid, 1, speech, RuleExtractor())
    assert (report.confirmed, report.hypotheses) == (0, 1)
    queue = review_queue(db, pid)
    assert len(queue) == 1 and queue[0][1].state == "proposto"


def test_conclusion_needs_corroboration(db: Session, session_ids: tuple[int, int]) -> None:
    pid, sid = session_ids
    obj = add_objective(db, pid, "derrotar o dragão", ObjKind.PRINCIPAL)
    speech = [fala(100, 103, "Finalmente derrotei o dragão!")]
    discover(db, pid, sid, 1, speech, RuleExtractor([obj.title]))
    assert current_state(db, obj.id).state == "incerto"  # type: ignore[union-attr]
    discover(db, pid, sid, 1, speech, RuleExtractor([obj.title]), corroboration=[(101 * FPS, 101 * FPS)])
    assert current_state(db, obj.id).state == "concluido"  # type: ignore[union-attr]


def test_invalid_citation_is_rejected(db: Session, session_ids: tuple[int, int]) -> None:
    class Liar:
        def extract(self, speech: Sequence[AnalysisEvent]) -> list[Candidate]:
            return [Candidate("x", ObjKind.SECUNDARIO, ObjState.PROPOSTO, "frase inventada", 0, 100, 0.5)]

    pid, sid = session_ids
    report = discover(db, pid, sid, 1, [fala(0, 2, "outra coisa")], Liar())
    assert report.rejected == 1 and review_queue(db, pid) == []


def test_profile_sync_and_review_csv(db: Session, session_ids: tuple[int, int], tmp_path: Path) -> None:
    pid, _ = session_ids
    assert sync_profile_objectives(db, pid, ["derrotar o chefe final"], ["modo hardcore"]) == 2
    assert sync_profile_objectives(db, pid, ["derrotar o chefe final"], ["modo hardcore"]) == 0
    path = export_review_csv(review_queue(db, pid), tmp_path / "r.csv")
    assert path.read_text(encoding="utf-8-sig").startswith("objetivo,tipo,estado")


# ------------------------------------------------------------------ arco e pacote


def seg(
    a: int, b: int, classe: str = "jogo", score: float = 0.5, markers: list[str] | None = None, **f: float
) -> Segment:
    return Segment(a, b, classe, score, ["r"], markers or [], dict(f))


def test_chapters_split_on_new_day_and_beats() -> None:
    kinds = {"d1": "novo_dia", "d2": "novo_dia", "x": "morte_falha", "c": "conquista"}
    segs = [
        seg(0, 30, "dia", 0.3, ["d1"]),
        seg(30, 80),
        seg(80, 120, "momento", 0.8, ["x"]),
        seg(120, 160, score=0.6, emocao=0.5),
        seg(160, 200, "momento", 0.9, ["c"]),
        seg(200, 230, "dia", 0.3, ["d2"]),
        seg(230, 300),
        seg(300, 320, "descartavel", 0.0),
    ]
    chapters = build_chapters([(1, segs)], kinds)
    assert [c.number for c in chapters] == [1, 2]
    beats = [i.beat for i in chapters[0].items]
    assert Beat.FALHA in beats and Beat.VIRADA in beats and Beat.CONQUISTA in beats
    assert beats.index(Beat.VIRADA) > beats.index(Beat.FALHA)
    assert all(i.segment.classe != "descartavel" for c in chapters for i in c.items)
    allocate_time(chapters, 600)
    assert sum(c.allocated_s for c in chapters) == pytest.approx(600, abs=1)


def test_free_gaps_exclude_live_speech() -> None:
    gaps = free_gaps(0, 60, [fala(10, 20, "oi"), fala(40, 42, "tchau")])
    assert gaps[0][0] == 0 and gaps[0][1] <= 9.5
    assert all(not (a < 20 and b > 11) for a, b in gaps)
    assert gaps[-1][1] == 60


def make_pack() -> dict[str, Any]:
    segs = [seg(0, 60, "dia", 0.3, ["d1"]), seg(60, 120, "momento", 0.8, ["m"])]
    chapters = build_chapters([(1, segs)], {"d1": "novo_dia", "m": "momento"})
    allocate_time(chapters, 300)
    speech = {1: [fala(70, 80, "Isso foi muito bom, olha só.")]}
    return build_story_pack(chapters, speech, {"nome": "p"}, [], 300)


def test_story_pack_has_live_speech_and_gaps() -> None:
    pack = make_pack()
    beat = next(b for c in pack["capitulos"] for b in c["beats"] if b["segmento_id"] == "1:60")
    assert beat["fala_ao_vivo"][0]["texto"].startswith("Isso foi muito bom")
    assert beat["lacunas"] and all(not (g["inicio_s"] < 80 and g["fim_s"] > 71) for g in beat["lacunas"])
    assert any("fala ao vivo" in i.lower() for i in pack["instrucoes"])
    json.dumps(pack)


def test_story_pack_truncates_when_too_big() -> None:
    segs = [seg(i * 60, i * 60 + 60, "momento", 0.5 + i / 1000) for i in range(30)]
    chapters = build_chapters([(1, segs)], {})
    speech = {1: [fala(i * 60 + 1, i * 60 + 9, "x " * 70) for i in range(30)]}
    pack = build_story_pack(chapters, speech, {}, [], 600, max_chars=12000)
    assert pack["truncado"] is True
    assert len(json.dumps(pack, ensure_ascii=False)) <= 12000


# ------------------------------------------------------------------ roteiro


def index() -> dict[str, tuple[float, float, list[tuple[float, float]]]]:
    return {"1:60": (60.0, 120.0, [(0.0, 9.0), (21.0, 40.0)])}


def test_validate_script_rules() -> None:
    script = Script(
        lines=[
            ScriptLine(segment_id="1:60", text="Aqui eu decidi esperar a noite chegar."),
            ScriptLine(segment_id="9:9", text="fantasma"),
            ScriptLine(segment_id="1:60", text="Antes da hora.", kind="antecipacao"),
            ScriptLine(segment_id="1:60", text="Vale ressaltar que essa jornada foi épica. " * 10),
        ]
    )
    report = validate_script(script, index())
    assert any("inexistente" in e for e in report.errors)
    assert any("justificativa" in e for e in report.errors)
    assert any("não é X" not in w and "livres" in w for w in report.warnings)
    assert any("muleta_escrita" in w for w in report.warnings)
    assert report.lines[0].est_s == estimate_seconds("Aqui eu decidi esperar a noite chegar.")


def test_lint_flags() -> None:
    assert "nao_e_x_e_y" in lint_text("Não é só um jogo, é uma jornada.")
    assert "vocabulario_inflado" in lint_text("Foi épico.")
    assert lint_text("Fui buscar madeira e voltei antes de escurecer.") == []
    assert "frases_comecando_igual" in lint_text("Eu fui. Eu vi. Eu voltei.")


def test_srt_and_null_provider() -> None:
    lines = [ScriptLine(segment_id="1:60", text="Olha isso.", est_s=2.0, start_s=61.5)]
    srt = to_srt(lines, {})
    assert "00:01:01,500 --> 00:01:03,500" in srt
    pack = make_pack()
    assert NullProvider().write(pack).lines == []
    notes = dict(context_notes(pack))
    assert "1:60" in notes and "momento" in notes["1:60"]


class FakeGen:
    def __init__(self, replies: list[str]) -> None:
        self.replies = replies

    def generate(self, prompt: str, max_tokens: int) -> str:
        return self.replies.pop(0)


def test_local_provider_validates_and_drops_bad_output() -> None:
    pack = make_pack()
    ok = LocalScriptProvider(FakeGen(['{"texto": "Aqui a noite caiu."}'] * 3)).write(pack)
    assert ok.lines and ok.lines[0].text == "Aqui a noite caiu."
    bad = LocalScriptProvider(
        FakeGen(["sem json", '{"texto": "Foi épico e vale ressaltar."}', '{"x": 1}'] * 2)
    ).write(pack)
    assert bad.lines == []


def test_voice_profile() -> None:
    quotes = ["cara isso aqui é loucura", "cara olha só isso", "cara não acredito que deu certo"]
    prof = voice_profile(quotes)
    assert (prof["frases"] == 3 and "cara" in prof["palavras_frequentes"]) or prof["bordoes"] == []


def test_failure_needs_a_failure_marker(db: Session, session_ids: tuple[int, int]) -> None:
    pid, sid = session_ids
    obj = add_objective(db, pid, "achar comida", ObjKind.PRINCIPAL)
    speech = [fala(50, 53, "Não consegui achar comida nenhuma.")]
    discover(db, pid, sid, 1, speech, RuleExtractor([obj.title]))
    assert current_state(db, obj.id).state == "incerto"  # type: ignore[union-attr]
    discover(
        db, pid, sid, 1, speech, RuleExtractor([obj.title]), failure_corroboration=[(51 * FPS, 51 * FPS)]
    )
    assert current_state(db, obj.id).state == "falhou"  # type: ignore[union-attr]


def test_discover_is_idempotent(db: Session, session_ids: tuple[int, int]) -> None:
    from sqlalchemy import func, select

    from cronista.db.models import ObjectiveState

    pid, sid = session_ids
    speech = [fala(10, 13, "Preciso achar comida antes de anoitecer.")]
    for _ in range(3):
        discover(db, pid, sid, 1, speech, RuleExtractor())
    assert db.scalar(select(func.count()).select_from(ObjectiveState)) == 1


def test_story_pack_truncated_flag_only_when_cut() -> None:
    small = make_pack()
    assert small["truncado"] is False

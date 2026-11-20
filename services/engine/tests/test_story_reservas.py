"""Janelas reservadas de gancho e fecho (histórico §67): fora das lacunas, no começo e no fim da timeline."""

from __future__ import annotations

import json
from pathlib import Path

from cronista.assembly.plan import EditPlan, build_edit_plan
from cronista.domain.frames import FPS
from cronista.mix.envelope import narration_cues
from cronista.relevance.engine import Segment
from cronista.story.arc import BeatedSegment, Chapter
from cronista.story.models import Beat, Script, ScriptLine, Span
from cronista.story.pack import build_story_pack
from cronista.story.script import CLOSE_ID, HOOK_ID, RESERVED_MAX_S, to_srt, validate_script
from cronista.story.service import save_script


def _plan() -> EditPlan:
    items = [
        BeatedSegment(
            Span(file_id=1, start_s=a, end_s=b), Segment(a, b, "conversa", 0.6, ["x"]), Beat.CONFLITO
        )
        for a, b in ((100, 130), (300, 340))
    ]
    return build_edit_plan([Chapter(1, items, 600.0)])


def _line(sid: str, text: str, est: float | None = None) -> ScriptLine:
    return ScriptLine(segment_id=sid, text=text, est_s=est)


def test_pacote_oferece_as_duas_janelas_so_com_capitulo() -> None:
    item = BeatedSegment(
        Span(file_id=1, start_s=10, end_s=40), Segment(10, 40, "conversa", 0.6, ["x"]), Beat.SETUP
    )
    pack = build_story_pack([Chapter(1, [item], 100.0)], {}, {"nome": "p", "jogo": ""}, [], 2400.0)
    assert [r["id"] for r in pack["reservas"]] == [HOOK_ID, CLOSE_ID]
    assert {r["id"]: r["max_s"] for r in pack["reservas"]} == RESERVED_MAX_S
    assert build_story_pack([], {}, {"nome": "p", "jogo": ""}, [], 2400.0)["reservas"] == []


def test_validacao_aceita_gancho_e_fecho_sem_lacuna_e_encadeia_as_falas() -> None:
    segments: dict[str, tuple[float, float, list[tuple[float, float]]]] = {"1:100": (100.0, 130.0, [])}
    script = Script(
        lines=[_line(HOOK_ID, "primeira", 4.0), _line(HOOK_ID, "segunda", 3.0), _line(CLOSE_ID, "fim", 2.0)]
    )
    report = validate_script(script, segments)
    assert report.ok
    assert [(x.segment_id, x.start_s) for x in report.lines] == [
        (HOOK_ID, 0.0),
        (HOOK_ID, 4.0),
        (CLOSE_ID, 0.0),
    ]
    assert any("janela reservada" in w for w in report.warnings)


def test_validacao_avisa_janela_estourada_e_recusa_antecipacao_no_gancho() -> None:
    long = Script(lines=[_line(HOOK_ID, "x", RESERVED_MAX_S[HOOK_ID] + 5)])
    assert any("o criador corta" in w for w in validate_script(long, {}).warnings)
    bad = Script(lines=[ScriptLine(segment_id=HOOK_ID, text="x", kind="antecipacao", justification="j")])
    assert not validate_script(bad, {}).ok


def test_fala_comum_continua_exigindo_lacuna() -> None:
    report = validate_script(Script(lines=[_line("1:100", "oi", 2.0)]), {"1:100": (100.0, 130.0, [])})
    assert not report.ok


def test_gancho_abre_a_timeline_e_fecho_termina_nela() -> None:
    plan = _plan()
    last = plan.items[-1].timeline_end
    lines = [
        ScriptLine(segment_id=HOOK_ID, text="a", est_s=4.0, start_s=0.0),
        ScriptLine(segment_id=HOOK_ID, text="b", est_s=3.0, start_s=4.0),
        ScriptLine(segment_id=CLOSE_ID, text="c", est_s=5.0, start_s=0.0),
    ]
    cues = narration_cues(plan.items, lines)
    first = min(i.timeline_start for i in plan.items)
    assert cues[0][:2] == (first, first + 4 * FPS)
    assert cues[1][:2] == (first + 4 * FPS, first + 7 * FPS)
    assert cues[-1][:2] == (last - 5 * FPS, last)


def test_srt_em_tempo_de_arquivo_usa_o_deslocamento_da_janela() -> None:
    lines = [ScriptLine(segment_id=HOOK_ID, text="a", est_s=2.0, start_s=1.0)]
    srt = to_srt(lines, {HOOK_ID: 100.0})
    assert "00:01:41,000 --> 00:01:43,000" in srt


def test_falas_reservadas_sem_start_s_se_encadeiam_na_timeline() -> None:
    """Roteiro não validado (lido por `montagem --script`): o encadeamento não depende do `roteiro-import`."""
    plan = _plan()
    first = min(i.timeline_start for i in plan.items)
    lines = [
        ScriptLine(segment_id=HOOK_ID, text="a", est_s=4.0),
        ScriptLine(segment_id=HOOK_ID, text="b", est_s=3.0),
    ]
    cues = narration_cues(plan.items, lines)
    assert [c[:2] for c in cues] == [(first, first + 4 * FPS), (first + 4 * FPS, first + 7 * FPS)]


def test_fecho_maior_que_a_timeline_nao_sai_antes_do_inicio() -> None:
    plan = _plan()
    first, last = min(i.timeline_start for i in plan.items), plan.items[-1].timeline_end
    long_s = (last - first) / FPS + 60
    cues = narration_cues(plan.items, [ScriptLine(segment_id=CLOSE_ID, text="x", est_s=long_s)])
    assert cues[0][0] == first and cues[0][1] == last


def test_convite_so_vale_nas_janelas_reservadas_e_pede_confirmacao() -> None:
    segments: dict[str, tuple[float, float, list[tuple[float, float]]]] = {
        "1:100": (100.0, 130.0, [(100.0, 110.0)])
    }
    ok = validate_script(
        Script(lines=[ScriptLine(segment_id=HOOK_ID, text="Deixa o like.", kind="convite")]), segments
    )
    assert ok.ok and any("convite do criador" in w for w in ok.warnings)
    bad = validate_script(
        Script(lines=[ScriptLine(segment_id="1:100", text="Deixa o like.", kind="convite")]), segments
    )
    assert not bad.ok and any("convite só vale" in e for e in bad.errors)
    assert "[CONVITE] Deixa o like." in to_srt(
        [ScriptLine(segment_id=HOOK_ID, text="Deixa o like.", kind="convite")], {}
    )


def test_save_script_posiciona_gancho_e_fecho_na_ordem_do_pacote(tmp_path: Path) -> None:
    """Dois arquivos, relógios diferentes: o gancho vai para o 1º trecho do pacote, não para o menor tempo."""
    pack = {
        "capitulos": [
            {
                "beats": [
                    {"segmento_id": "1:500", "inicio_s": 500.0, "fim_s": 530.0, "lacunas": []},
                    {"segmento_id": "2:5", "inicio_s": 5.0, "fim_s": 40.0, "lacunas": []},
                ]
            }
        ]
    }
    (tmp_path / "story-pack.json").write_text(json.dumps(pack), encoding="utf-8")
    script = Script(
        lines=[
            ScriptLine(segment_id=HOOK_ID, text="abre", est_s=2.0),
            ScriptLine(segment_id=CLOSE_ID, text="fecha", est_s=3.0),
        ]
    )
    save_script(tmp_path, script)
    srt = (tmp_path / "roteiro.srt").read_text(encoding="utf-8")
    assert "00:08:20,000 --> 00:08:22,000" in srt  # gancho em 500 s (1º trecho do pacote)
    assert "00:00:37,000 --> 00:00:40,000" in srt  # fecho termina em 40 s (último trecho do pacote)

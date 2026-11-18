"""Regressões da auditoria 10A (bloco B): cada teste falhava antes da correção."""

from __future__ import annotations

from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource
from cronista.domain.frames import FPS
from cronista.story.models import Script, ScriptLine
from cronista.story.objectives import RuleExtractor
from cronista.story.script import LocalScriptProvider, free_gaps, validate_script
from tests.test_story import FakeGen, fala


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

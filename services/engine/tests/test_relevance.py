"""Motor de relevância (Fase 4) com eventos sintéticos: segmentação, lookback, nota explicável e métricas."""

from __future__ import annotations

import itertools

from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource
from cronista.domain.frames import FPS
from cronista.gabarito import Annotation
from cronista.relevance.engine import (
    MarkerRef,
    RelevanceParams,
    Segment,
    build_segments,
    is_kept,
    kept_seconds,
    speech_blocks,
)
from cronista.relevance.quality import evaluate_relevance, render_quality
from cronista.relevance.service import events_to_segments, segments_to_events


def ev(kind: str, a: float, b: float, conf: float = 0.8, **payload: object) -> AnalysisEvent:
    e = Evidence(
        source=EvidenceSource.EVENTO,
        start_frame=round(a * FPS),
        end_frame=round(b * FPS),
        confidence=conf,
        model="m",
        model_version="1",
        params_hash="h",
    )
    return AnalysisEvent(kind=kind, evidence=e, payload=dict(payload))


def talk(a: int, b: int) -> list[AnalysisEvent]:
    return [ev("fala", s, s + 2) for s in range(a, b, 2)]


def by_class(segs: list[Segment], classe: str) -> list[Segment]:
    return [s for s in segs if s.classe == classe]


def test_speech_blocks_join_small_gaps() -> None:
    import numpy as np

    speech = np.zeros(30)
    speech[2:6] = 1
    speech[8:10] = 1  # lacuna de 2 s: junta
    speech[20:22] = 1  # lacuna de 10 s: separa
    assert speech_blocks(speech, 4) == [(2, 10), (20, 22)]


def test_marker_has_lookback_and_makes_a_moment() -> None:
    events = talk(60, 100)
    segs = build_segments(events, [MarkerRef("m1", "momento", 80.0)], 300.0)
    moment = by_class(segs, "momento")
    assert len(moment) == 1
    m = moment[0]
    assert m.start_s < 80 <= m.end_s and m.start_s <= 80 - 15  # o toque vem depois do acontecido
    assert m.markers == ["m1"] and m.score > 0.4
    assert any(r.startswith("marcadores: momento") for r in m.razoes)


def test_segments_cover_the_file_without_overlap() -> None:
    events = [ev("loading", 0, 20), *talk(30, 90), ev("menu", 150, 190), ev("risada", 100, 102)]
    segs = build_segments(events, [MarkerRef("a", "engracado", 101.0)], 400.0)
    assert segs[0].start_s == 0 and segs[-1].end_s == 400
    for prev, cur in itertools.pairwise(segs):
        assert prev.end_s <= cur.start_s
    assert sum(s.duration_s for s in segs) <= 400


def test_pause_is_discarded_and_penalised() -> None:
    events = [ev("menu", 10, 70)]
    segs = build_segments(events, [], 100.0)
    discarded = by_class(segs, "descartavel")
    assert discarded and discarded[0].duration_s >= 50
    assert any("tela dominante: menu" in r for r in discarded[0].razoes)


def test_quiet_long_stretch_is_farm_and_talk_is_not() -> None:
    events = talk(0, 40)
    segs = build_segments(events, [], 400.0, RelevanceParams(max_s=400))
    assert by_class(segs, "farm"), "trecho longo sem fala nem emoção vira farm"
    assert not any(s.classe == "farm" and s.start_s < 30 for s in segs)


def test_emotion_raises_score_without_a_marker() -> None:
    quiet = build_segments(talk(0, 30), [], 40.0)
    loud = build_segments([*talk(0, 30), ev("risada", 10, 12, 0.9), ev("exclamacao", 20, 21, 0.9)], [], 40.0)
    assert max(s.score for s in loud) > max(s.score for s in quiet)


def test_novel_context_adds_score() -> None:
    events = [ev("contexto", 0, 30, context_id=0), ev("contexto", 30, 60, context_id=1), *talk(0, 60)]
    segs = build_segments(events, [], 60.0)
    assert any(any("novidade" in r for r in s.razoes) for s in segs)


def test_events_roundtrip() -> None:
    segs = build_segments(talk(0, 40), [MarkerRef("x", "conquista", 30.0)], 100.0)
    back = events_to_segments(segments_to_events(segs, RelevanceParams()))
    assert [(s.start_s, s.end_s, s.classe) for s in back] == [(s.start_s, s.end_s, s.classe) for s in segs]


def test_quality_metrics_and_product() -> None:
    events = talk(0, 40)
    segs = build_segments(events, [MarkerRef("x", "momento", 30.0)], 600.0, RelevanceParams(max_s=600))
    gab = [
        Annotation(1, 25 * FPS, 32 * FPS, "momento", ""),
        Annotation(2, 200 * FPS, 500 * FPS, "farm", ""),
        Annotation(3, 580 * FPS, 590 * FPS, "momento", ""),
    ]
    q = evaluate_relevance(gab, segs, top_n=5)
    assert q.moments_expected == 2 and q.moments_in_top >= 1
    assert q.farm_recall is not None and q.farm_recall > 0.5
    assert "meta 85%" in render_quality(q)
    assert sum(kept_seconds(s) for s in segs) > 0


def test_marker_beats_pause_discard() -> None:
    """Cinemática lida como menu: o marcador do criador impede a classe `descartavel`."""
    events = [ev("menu", 0, 100)]
    segs = build_segments(events, [MarkerRef("c", "cinematica", 50.0)], 120.0)
    marked = [s for s in segs if "c" in s.markers]
    assert marked and all(s.classe != "descartavel" for s in marked)
    assert by_class(build_segments(events, [], 120.0), "descartavel")


def test_kept_criterion_is_single_and_reads_keep_score() -> None:
    """B9: painel, arco e qualidade usam a mesma regra; `keep_score` do parâmetro vale."""
    weak = Segment(0, 100, "jogo", 0.40)
    assert is_kept(weak) and not is_kept(weak, keep_score=0.5)
    assert kept_seconds(weak) == 45.0 and kept_seconds(weak, 0.5) == 0.0
    assert not is_kept(Segment(0, 10, "descartavel", 0.9, markers=["x"]))
    assert is_kept(Segment(0, 10, "jogo", 0.0, markers=["x"]))  # o voto do criador
    assert kept_seconds(Segment(0, 100, "farm", 0.0)) == 10.0  # timelapse 10x


def test_lookback_is_a_param_and_a_profile_can_change_it() -> None:
    """B13: o lookback sai de `RelevanceParams` (e o perfil o ajusta no grupo `relevance`)."""
    from cronista.profiles import GameProfile, apply_thresholds

    events = talk(0, 40)
    marker = [MarkerRef("x", "momento", 100.0)]
    default = build_segments(events, marker, 200.0, RelevanceParams(snap_s=0))
    longer = apply_thresholds(
        GameProfile(name="p", thresholds={"relevance": {"lookback_momento": 40.0}}),
        "relevance",
        RelevanceParams(snap_s=0),
    )
    wide = build_segments(events, marker, 200.0, longer)

    def start(segs: list[Segment]) -> int:
        return next(s.start_s for s in segs if "x" in s.markers)

    assert start(default) == 75 and start(wide) == 60
    assert RelevanceParams().lookback("tipo-sem-campo") == 20.0


def test_merged_windows_respect_max_s_and_never_cross_novo_dia() -> None:
    """B14: a fusão não passa de `max_s` e o `novo_dia` mantém o início do próprio trecho."""
    params = RelevanceParams(snap_s=0, max_s=60)
    markers = [MarkerRef(str(i), "momento", 100.0 + 15 * i) for i in range(6)]
    segs = build_segments([], markers, 400.0, params)
    assert all(s.duration_s <= 60 for s in segs if s.markers)
    assert {m for s in segs for m in s.markers} == {m.marker_id for m in markers}
    marks = [MarkerRef("a", "momento", 100.0), MarkerRef("d", "novo_dia", 105.0)]
    segs = build_segments([], marks, 300.0, RelevanceParams(snap_s=0))
    day = next(s for s in segs if "d" in s.markers)
    assert day.start_s == 100  # lookback de 5 s do `novo_dia`, e o momento anterior terminou ali
    assert not any(s.start_s < day.start_s < s.end_s for s in segs)

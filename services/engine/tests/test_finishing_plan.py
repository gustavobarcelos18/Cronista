"""Plano de acabamento (8B). Sem pytest e sem pydantic de propósito: roda só com a biblioteca padrão."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from cronista.domain.frames import FPS
from cronista.domain.tracks import Track
from cronista.finishing.effects import EffectKind, EffectMode
from cronista.finishing.plan import (
    AssetRef,
    CardRef,
    FinishPlan,
    Moment,
    build_finish_plan,
    chapter_mood,
    intensity_of,
    snap_music,
)

MIN = FPS * 60


@dataclass(frozen=True)
class Policy:
    mode: EffectMode = EffectMode.EDITAVEL
    max_per_minute: float = 2.0
    min_score: float = 0.5


def policies(**changes: Policy) -> dict[EffectKind, Policy]:
    base = {kind: Policy(max_per_minute=60.0, min_score=0.0) for kind in EffectKind}
    for name, policy in changes.items():
        base[EffectKind(name)] = policy
    return base


def only(**changes: Policy) -> dict[EffectKind, Policy]:
    """Tudo desligado, menos o que foi pedido (isola o efeito testado do teto somado)."""
    base = {kind: Policy(max_per_minute=0.0) for kind in EffectKind}
    for name, policy in changes.items():
        base[EffectKind(name)] = policy
    return base


def moment(
    n: int, *, score: float = 0.9, at_s: float | None = None, beat: str = "conflito", **kw: object
) -> Moment:
    start = round((at_s if at_s is not None else n * 120.0) * FPS)
    values: dict[str, object] = {
        "id": f"m{n}",
        "chapter": 1,
        "start": start,
        "frames": 10 * FPS,
        "score": score,
        "beat": beat,
        "live": True,
    }
    values.update(kw)
    return Moment(**values)  # type: ignore[arg-type]


def sfx(item_id: str, *tags: str) -> AssetRef:
    return AssetRef(item_id, "sfx", frozenset(tags))


def test_fps_matches_domain() -> None:
    assert FPS == 60


def test_intensity_grows_with_score() -> None:
    assert intensity_of(0.5, 0.5) == 0.0
    assert intensity_of(1.0, 0.5) == 1.0
    assert 0 < intensity_of(0.75, 0.5) < 1
    assert intensity_of(0.2, 0.5) == 0.0


def test_below_min_score_applies_nothing() -> None:
    plan = build_finish_plan([moment(1, score=0.4)], only(zoom=Policy(min_score=0.5)), total_frames=20 * MIN)
    assert plan.of(EffectKind.ZOOM) == []


def test_zero_budget_disables_effect() -> None:
    pol = only(zoom=Policy(max_per_minute=0.0, min_score=0.0))
    plan = build_finish_plan([moment(1)], pol, total_frames=20 * MIN)
    assert plan.of(EffectKind.ZOOM) == []


def test_zoom_scales_with_score_and_stays_inside_moment() -> None:
    pol = only(zoom=Policy(min_score=0.5))
    plan = build_finish_plan([moment(1, score=0.55), moment(2, score=1.0)], pol, total_frames=20 * MIN)
    low, high = plan.of(EffectKind.ZOOM)
    assert float(low.params["escala"]) < float(high.params["escala"]) <= 1.25
    for item, m in ((low, moment(1, score=0.55)), (high, moment(2, score=1.0))):
        assert m.start <= item.start and item.end <= m.end
        assert item.track == Track.V2


def test_no_zoom_on_timelapse() -> None:
    plan = build_finish_plan([moment(1, live=False)], policies(), total_frames=20 * MIN)
    assert plan.of(EffectKind.ZOOM) == [] and plan.of(EffectKind.SHAKE) == []


def test_per_effect_spacing_keeps_best_scores() -> None:
    # Três momentos a 10 s um do outro, 2 por minuto => 30 s de espaçamento: só o de maior nota passa.
    ms = [moment(1, score=0.7, at_s=0), moment(2, score=0.95, at_s=10), moment(3, score=0.8, at_s=20)]
    plan = build_finish_plan(ms, only(zoom=Policy(max_per_minute=2.0, min_score=0.5)), total_frames=MIN)
    zooms = plan.of(EffectKind.ZOOM)
    assert [z.moment_id for z in zooms] == ["m2"]
    assert any("zoom: 2 candidato" in w for w in plan.warnings)


def test_spacing_never_violated_for_any_effect() -> None:
    ms = [moment(n, score=0.5 + (n % 5) / 10, at_s=n * 7.0) for n in range(40)]
    pol = only(zoom=Policy(max_per_minute=3.0, min_score=0.5))
    plan = build_finish_plan(ms, pol, total_frames=10 * MIN)
    starts = sorted(z.start for z in plan.of(EffectKind.ZOOM))
    assert starts, "esperava algum zoom"
    assert all(b - a >= MIN / 3.0 for a, b in pairwise(starts))


def test_total_cap_counts_applied_not_suggested() -> None:
    ms = [moment(n, score=0.9, at_s=n * 3.0, tags=frozenset({"morte_falha"}), beat="falha") for n in range(6)]
    pol = only(
        zoom=Policy(max_per_minute=60.0, min_score=0.0),
        shake=Policy(max_per_minute=60.0, min_score=0.0),
        freeze_texto=Policy(mode=EffectMode.SUGERIR, max_per_minute=60.0, min_score=0.0),
    )
    plan = build_finish_plan(ms, pol, total_frames=MIN, max_total_per_minute=4)
    applied = [i for i in plan.items if i.mode != EffectMode.SUGERIR]
    assert len(applied) <= 4
    # nenhuma janela de 60 s com mais de 4 efeitos aplicados
    for left in applied:
        assert sum(1 for i in applied if left.start <= i.start < left.start + MIN) <= 4
    assert plan.of(EffectKind.FREEZE_TEXTO), "sugestões não disputam o teto"


def test_sfx_needs_matching_asset_and_rotates() -> None:
    ms = [moment(n, beat="falha", tags=frozenset({"morte_falha"}), at_s=n * 60.0) for n in range(4)]
    pol = only(sfx=Policy(max_per_minute=60.0, min_score=0.0))
    none = build_finish_plan(ms, pol, total_frames=10 * MIN, assets=[sfx("x", "conquista")])
    assert none.of(EffectKind.SFX) == []
    assert any("tag 'morte'" in w for w in none.warnings)
    plan = build_finish_plan(ms, pol, total_frames=10 * MIN, assets=[sfx("b", "morte"), sfx("a", "morte")])
    assert [i.asset_id for i in plan.of(EffectKind.SFX)] == ["a", "b", "a", "b"]
    assert all(i.frames == 0 and i.track == Track.A5 for i in plan.of(EffectKind.SFX))


def test_meme_only_on_funny_marker() -> None:
    meme = AssetRef("risada", "meme")
    pol = only(sfx_meme=Policy(max_per_minute=60.0, min_score=0.0))
    ms = [moment(1, tags=frozenset({"engracado"})), moment(2)]
    plan = build_finish_plan(ms, pol, total_frames=10 * MIN, assets=[meme])
    assert [i.moment_id for i in plan.of(EffectKind.SFX_MEME)] == ["m1"]


def test_death_counter_numbers_every_death_even_if_cut_by_budget() -> None:
    ms = [moment(n, tags=frozenset({"morte_falha"}), at_s=n * 30.0, score=0.5 + n / 20) for n in range(1, 4)]
    pol = only(contador_mortes=Policy(mode=EffectMode.RENDERIZADO, max_per_minute=1.0, min_score=0.0))
    plan = build_finish_plan(ms, pol, total_frames=10 * MIN)
    # 1 por minuto: a morte 3 (maior nota) entra, a 2 cai por espaçamento e a 1 ainda cabe; a ordem é a real
    assert sorted(int(i.params["ordem"]) for i in plan.of(EffectKind.CONTADOR_MORTES)) == [1, 3]


def test_music_by_mood_snapped_to_whole_bars() -> None:
    ms = [moment(1, beat="conflito", at_s=0, frames=100 * FPS)]
    track = AssetRef("tensa", "musica", frozenset(), mood="tenso", bpm=120.0)
    plan = build_finish_plan(ms, only(musica=Policy(min_score=0.0)), total_frames=2 * MIN, assets=[track])
    (item,) = plan.of(EffectKind.MUSICA)
    assert item.asset_id == "tensa" and item.track == Track.A4
    # 120 bpm = 30 quadros por tempo; 100 s = 6000 quadros = 200 tempos = 50 compassos
    assert item.params["compassos"] == 50 and item.frames == 6000
    assert item.frames <= 100 * FPS


def test_music_prefers_brand_theme_and_warns_without_track() -> None:
    ms = [moment(1, beat="conflito", at_s=0, frames=60 * FPS)]
    a = AssetRef("a", "musica", frozenset(), mood="tenso", bpm=100.0)
    b = AssetRef("b", "musica", frozenset(), mood="outro", bpm=100.0)
    pol = only(musica=Policy(min_score=0.0))
    plan = build_finish_plan(ms, pol, total_frames=MIN, assets=[a, b], preferred_music={"tenso": ["b"]})
    assert plan.of(EffectKind.MUSICA)[0].asset_id == "b"
    empty = build_finish_plan(ms, pol, total_frames=MIN, assets=[])
    assert empty.of(EffectKind.MUSICA) == []
    assert any("clima 'tenso'" in w for w in empty.warnings)


def test_snap_music_and_chapter_mood() -> None:
    assert snap_music(FPS, 120.0) is None  # 1 s não tem um compasso
    assert snap_music(4 * FPS, 120.0) == (240, 2)  # 8 tempos de 30 quadros = 2 compassos
    assert chapter_mood([moment(1, beat="setup"), moment(2, beat="conquista", frames=30 * FPS)]) == "epico"
    assert chapter_mood([]) == "calmo"


def test_cards_and_lut_are_structural() -> None:
    pol = only(
        cartela_dia=Policy(max_per_minute=1.0, min_score=0.0),
        cor_lut=Policy(max_per_minute=60.0, min_score=0.0),
    )
    plan = build_finish_plan(
        [moment(1)],
        pol,
        total_frames=MIN,
        cards=[CardRef(1, 0, 180), CardRef(2, 600, 180)],
        lut="luts/x.cube",
    )
    assert [i.start for i in plan.of(EffectKind.CARTELA_DIA)] == [0, 600]
    (lut,) = plan.of(EffectKind.COR_LUT)
    assert lut.frames == MIN and lut.params["lut"] == "luts/x.cube"
    assert not build_finish_plan([moment(1)], pol, total_frames=MIN).of(EffectKind.COR_LUT)


def test_deterministic_and_hash_changes_with_input() -> None:
    ms = [moment(n, score=0.6 + n / 20, at_s=n * 25.0, tags=frozenset({"engracado"})) for n in range(1, 6)]
    pol = only(zoom=Policy(max_per_minute=2.0, min_score=0.5))
    a = build_finish_plan(ms, pol, total_frames=5 * MIN)
    b = build_finish_plan(list(reversed(ms)), pol, total_frames=5 * MIN)
    assert a.to_json() == b.to_json()
    c = build_finish_plan(ms, only(zoom=Policy(max_per_minute=3.0, min_score=0.5)), total_frames=5 * MIN)
    assert a.input_hash != c.input_hash


def test_items_stay_inside_timeline() -> None:
    ms = [moment(1, at_s=0, frames=5 * FPS), moment(2, at_s=100, frames=5 * FPS)]
    plan: FinishPlan = build_finish_plan(ms, policies(), total_frames=105 * FPS)
    for item in plan.items:
        assert item.start >= 0 and item.start + item.frames <= 105 * FPS


def test_effects_without_an_applied_form_are_downgraded_with_a_warning() -> None:
    """C7 (auditoria 10A): piada visual e freeze em `editavel` ocupavam vaga sem aparecer no vídeo."""
    pol = only(
        piada_visual=Policy(EffectMode.EDITAVEL, 6, 0.0), freeze_texto=Policy(EffectMode.RENDERIZADO, 6, 0.0)
    )
    plan = build_finish_plan(
        [moment(1, tags=frozenset({"engracado"}), beat="falha")], pol, total_frames=20 * MIN
    )
    assert plan.items and all(i.mode == EffectMode.SUGERIR for i in plan.items)
    assert any("rebaixado para sugerir" in w for w in plan.warnings)

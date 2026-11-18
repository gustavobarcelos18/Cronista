"""Plano de acabamento (Fase 8B): momentos da montagem → efeitos por trilha, dentro do orçamento.

Puro e determinístico (mesma entrada, mesmo plano) e só com a biblioteca padrão: não lê banco, não roda
FFmpeg e não conhece pydantic. As políticas entram por `PolicyLike` (o `EffectPolicy` do brand kit já
cumpre) e a biblioteca pessoal entra como `AssetRef`; o encaixe com o banco e o brand kit fica em
`finishing/service.py`.

Regras (plano 6.4, histórico §40 e §57):
- cada efeito só considera momentos com nota >= `min_score`; `max_per_minute == 0` desliga o efeito;
- **orçamento por efeito** = espaçamento mínimo de `60 / max_per_minute` s entre dois do mesmo efeito
  (variação garantida, não só média) e **teto somado** por minuto para o que é aplicado (editável ou
  renderizado); `sugerir` é só marcador e não entra no teto;
- a intensidade (0 a 1) cresce com a nota; quando há mais candidatos que vagas, ganham as maiores notas;
- sem item adequado na biblioteca, nada é aplicado (e o plano avisa);
- música: uma trilha por capítulo, escolhida pelo clima, cortada em compassos inteiros no BPM;
- cartela de dia, música e LUT são estruturais: não entram no espaçamento nem no teto.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from enum import StrEnum
from typing import Any, Protocol

from cronista.domain.frames import FPS, seconds_to_frame
from cronista.finishing.effects import EffectKind, EffectMode

"""Igual a `cronista.domain.frames.FPS` (conferido em teste); repetido para não importar pydantic."""

PLAN_VERSION = 1

STRUCTURAL = frozenset({EffectKind.COR_LUT, EffectKind.MUSICA, EffectKind.CARTELA_DIA})
"""Efeitos que seguem a estrutura da montagem e não disputam vaga no orçamento por minuto."""

NEEDS_ASSET = frozenset({EffectKind.SFX, EffectKind.SFX_MEME, EffectKind.MUSICA})

BEAT_MOOD = {"setup": "calmo", "conflito": "tenso", "falha": "tenso", "virada": "epico", "conquista": "epico"}
"""Clima sugerido pelo beat narrativo (Fase 5); o criador pode trocar as trilhas por clima no brand kit."""


class Track(StrEnum):
    V1 = "V1"
    V2 = "V2"
    V4 = "V4"
    V5 = "V5"
    A4 = "A4"
    A5 = "A5"


TRACK_OF: dict[EffectKind, Track] = {
    EffectKind.ZOOM: Track.V2,
    EffectKind.SHAKE: Track.V2,
    EffectKind.CONTADOR_MORTES: Track.V4,
    EffectKind.FREEZE_TEXTO: Track.V4,
    EffectKind.PIADA_VISUAL: Track.V4,
    EffectKind.BARRA_PROGRESSO: Track.V4,
    EffectKind.LEGENDA_PONTUAL: Track.V4,
    EffectKind.CARTELA_DIA: Track.V5,
    EffectKind.COR_LUT: Track.V1,
    EffectKind.MUSICA: Track.A4,
    EffectKind.SFX: Track.A5,
    EffectKind.SFX_MEME: Track.A5,
}

NOT_IN_8B = frozenset({EffectKind.BARRA_PROGRESSO, EffectKind.LEGENDA_PONTUAL})
"""Dependem de dados que o plano não tem (progresso da série; palavras do Whisper): ficam para depois da 8."""


class PolicyLike(Protocol):
    @property
    def mode(self) -> EffectMode: ...
    @property
    def max_per_minute(self) -> float: ...
    @property
    def min_score(self) -> float: ...


@dataclass(frozen=True)
class FinishParams:
    zoom_s: float = 1.5
    shake_s: float = 0.6
    counter_s: float = 3.0
    freeze_s: float = 1.5
    joke_s: float = 2.0
    min_bars_music: int = 1
    """Compassos inteiros mínimos para um capítulo receber música (4 tempos por compasso)."""


@dataclass(frozen=True)
class Moment:
    """Um trecho da montagem em tempo de timeline (quadros), com a nota e os sinais do criador."""

    id: str
    chapter: int
    start: int
    frames: int
    score: float
    beat: str
    live: bool
    """Gameplay ao vivo ou montagem; timelapse e B-roll não recebem zoom nem shake."""
    tags: frozenset[str] = frozenset()
    """Tipos de marcador do criador no trecho (`morte_falha`, `engracado`, `conquista`...)."""
    peak: int | None = None
    """Quadro do pico na timeline; sem ele vale o meio do trecho."""

    @property
    def end(self) -> int:
        return self.start + self.frames

    @property
    def peak_frame(self) -> int:
        return self.peak if self.peak is not None else self.start + self.frames // 2


@dataclass(frozen=True)
class AssetRef:
    """Item da biblioteca pessoal visto pelo plano (só os que têm licença para o uso pedido)."""

    id: str
    kind: str
    tags: frozenset[str] = frozenset()
    mood: str | None = None
    bpm: float | None = None


@dataclass(frozen=True)
class CardRef:
    chapter: int
    start: int
    frames: int


@dataclass(frozen=True)
class FinishItem:
    id: str
    kind: EffectKind
    mode: EffectMode
    track: Track
    start: int
    frames: int
    """Duração na timeline; 0 = a do arquivo de áudio (SFX)."""
    intensity: float
    chapter: int
    moment_id: str
    asset_id: str | None
    params: dict[str, float | int | str]
    reason: str

    @property
    def end(self) -> int:
        return self.start + self.frames


@dataclass
class FinishPlan:
    items: list[FinishItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    input_hash: str = ""

    def of(self, kind: EffectKind) -> list[FinishItem]:
        return [i for i in self.items if i.kind == kind]

    def summary(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for item in self.items:
            out.setdefault(item.kind.value, {}).setdefault(item.mode.value, 0)
            out[item.kind.value][item.mode.value] += 1
        return out

    def to_json(self) -> str:
        data: dict[str, Any] = {
            "versao": PLAN_VERSION,
            "fps": FPS,
            "entrada_hash": self.input_hash,
            "itens": [asdict(i) for i in self.items],
            "resumo": self.summary(),
            "avisos": self.warnings,
        }
        return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)


@dataclass(frozen=True)
class _Candidate:
    kind: EffectKind
    start: int
    frames: int
    score: float
    intensity: float
    moment: Moment
    pool: tuple[str, ...]
    params: dict[str, float | int | str]
    reason: str


def intensity_of(score: float, min_score: float) -> float:
    """0 na nota mínima, 1 na nota máxima: morte boba ganha efeito leve, o chefe ganha o pacote completo."""
    if min_score >= 1:
        return 1.0
    return min(1.0, max(0.0, (score - min_score) / (1 - min_score)))


def _canon(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _canon(asdict(value))
    if isinstance(value, Mapping):
        return {str(k): _canon(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (set, frozenset)):
        return sorted(_canon(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    return value


def input_hash(*parts: Any) -> str:
    return hashlib.sha256(
        json.dumps(_canon(list(parts)), sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _window(moment: Moment, start: int, frames: int, total: int) -> tuple[int, int]:
    """Janela do efeito dentro do trecho (e da timeline); trecho curto encolhe o efeito, nunca o desloca."""
    frames = min(frames, moment.frames)
    start = max(moment.start, min(start, moment.end - frames))
    end = min(start + frames, total)
    return start, max(0, end - start)


def _sfx_tag(moment: Moment) -> str | None:
    if "morte_falha" in moment.tags:
        return "morte"
    if "conquista" in moment.tags or moment.beat == "conquista":
        return "conquista"
    if moment.beat == "virada":
        return "virada"
    if moment.beat == "falha":
        return "impacto"
    return None


def chapter_mood(moments: Sequence[Moment]) -> str:
    """Clima dominante do capítulo (peso = duração); empate resolvido por ordem alfabética."""
    weight: Counter[str] = Counter()
    for m in moments:
        weight[BEAT_MOOD.get(m.beat, "calmo")] += m.frames
    best = max(weight.values(), default=0)
    return min((mood for mood, w in weight.items() if w == best), default="calmo")


def snap_music(chapter_frames: int, bpm: float, min_bars: int = 1) -> tuple[int, int] | None:
    """Duração da trilha em compassos inteiros (4/4) que cabem no capítulo: `(quadros, compassos)`."""
    beat_frames = FPS * 60 / bpm
    bars = math.floor(chapter_frames / beat_frames) // 4
    if bars < min_bars:
        return None
    return round(bars * 4 * beat_frames), bars


def _moment_candidates(
    moments: Sequence[Moment],
    policies: Mapping[EffectKind, PolicyLike],
    assets: Sequence[AssetRef],
    total: int,
    params: FinishParams,
    warnings: set[str],
) -> list[_Candidate]:
    death_moments = sorted((m for m in moments if "morte_falha" in m.tags), key=lambda m: (m.start, m.id))
    deaths = {m.id: n for n, m in enumerate(death_moments, start=1)}
    sfx = sorted((a for a in assets if a.kind == "sfx"), key=lambda a: a.id)
    memes = sorted((a for a in assets if a.kind == "meme"), key=lambda a: a.id)
    out: list[_Candidate] = []

    def policy_for(kind: EffectKind, m: Moment) -> PolicyLike | None:
        policy = policies.get(kind)
        if policy is None or policy.max_per_minute <= 0 or kind in NOT_IN_8B or kind in STRUCTURAL:
            return None
        return policy if m.score >= policy.min_score else None

    def add(
        kind: EffectKind,
        m: Moment,
        policy: PolicyLike,
        dur_s: float,
        extra: dict[str, float | int | str],
        reason: str,
        *,
        pool: tuple[str, ...] = (),
        centered: bool = True,
    ) -> None:
        frames = seconds_to_frame(dur_s)
        wanted = m.peak_frame - frames // 2 if centered else m.peak_frame
        start, size = _window(m, wanted, frames, total)
        if (size <= 0 and frames > 0) or start >= total:
            return
        intensity = intensity_of(m.score, policy.min_score)
        out.append(_Candidate(kind, start, size, m.score, intensity, m, pool, extra, reason))

    def level(m: Moment, policy: PolicyLike) -> float:
        return intensity_of(m.score, policy.min_score)

    for m in sorted(moments, key=lambda m: (m.start, m.id)):
        if (policy := policy_for(EffectKind.ZOOM, m)) and m.live:
            extra: dict[str, float | int | str] = {
                "escala": round(1.05 + 0.20 * level(m, policy), 3),
                "easing": "ease_in_out",
            }
            add(EffectKind.ZOOM, m, policy, params.zoom_s, extra, f"nota {m.score:.2f} em {m.beat}")
        impact = "morte_falha" in m.tags or m.beat == "falha"
        if (policy := policy_for(EffectKind.SHAKE, m)) and m.live and impact:
            shake: dict[str, float | int | str] = {"amplitude_px": round(4 + 12 * level(m, policy), 1)}
            add(EffectKind.SHAKE, m, policy, params.shake_s, shake, f"impacto de {m.beat}")
        if policy := policy_for(EffectKind.SFX, m):
            tag = _sfx_tag(m)
            if tag is not None:
                pool = tuple(a.id for a in sfx if tag in a.tags)
                if pool:
                    gain: dict[str, float | int | str] = {
                        "ganho_db": round(-12 + 9 * level(m, policy), 1),
                        "tag": tag,
                    }
                    add(EffectKind.SFX, m, policy, 0, gain, f"SFX '{tag}' no pico", pool=pool, centered=False)
                else:
                    warnings.add(f"sfx: nenhum item com a tag '{tag}' na biblioteca")
        if (policy := policy_for(EffectKind.SFX_MEME, m)) and "engracado" in m.tags:
            if memes:
                meme_gain: dict[str, float | int | str] = {"ganho_db": round(-15 + 9 * level(m, policy), 1)}
                pool = tuple(a.id for a in memes)
                add(
                    EffectKind.SFX_MEME,
                    m,
                    policy,
                    0,
                    meme_gain,
                    "marcado como engraçado",
                    pool=pool,
                    centered=False,
                )
            else:
                warnings.add("sfx_meme: nenhum item do tipo 'meme' na biblioteca")
        if (policy := policy_for(EffectKind.PIADA_VISUAL, m)) and "engracado" in m.tags:
            add(EffectKind.PIADA_VISUAL, m, policy, params.joke_s, {}, "marcado como engraçado")
        if (policy := policy_for(EffectKind.FREEZE_TEXTO, m)) and m.beat in ("falha", "conquista"):
            add(EffectKind.FREEZE_TEXTO, m, policy, params.freeze_s, {}, f"pico de {m.beat}")
        if (policy := policy_for(EffectKind.CONTADOR_MORTES, m)) and m.id in deaths:
            order: dict[str, float | int | str] = {"ordem": deaths[m.id]}
            add(
                EffectKind.CONTADOR_MORTES,
                m,
                policy,
                params.counter_s,
                order,
                f"morte nº {deaths[m.id]}",
                centered=False,
            )
    return out


def _min_gap(policy: PolicyLike) -> float:
    return FPS * 60 / policy.max_per_minute


def _fits_total(starts: list[int], new: int, cap: int) -> bool:
    """Nenhuma janela de 60 s que comece em um dos efeitos passa de `cap` efeitos."""
    pool = sorted([*starts, new])
    return all(sum(1 for s in pool if left <= s < left + FPS * 60) <= cap for left in pool)


def _select(
    candidates: list[_Candidate],
    policies: Mapping[EffectKind, PolicyLike],
    max_total_per_minute: float,
    warnings: set[str],
) -> list[tuple[_Candidate, str | None]]:
    """Escolhe, por nota, os candidatos que cabem no orçamento. Devolve o item e o asset (rodízio)."""
    cap = max(1, math.floor(max_total_per_minute))
    accepted: list[tuple[_Candidate, str | None]] = []
    used: Counter[str] = Counter()
    dropped: Counter[EffectKind] = Counter()
    ordered = sorted(candidates, key=lambda c: (-c.score, c.start, c.kind.value))
    for c in ordered:
        policy = policies[c.kind]
        gap = _min_gap(policy)
        if any(a.kind == c.kind and abs(a.start - c.start) < gap for a, _ in accepted):
            dropped[c.kind] += 1
            continue
        counted = policy.mode != EffectMode.SUGERIR
        if counted and not _fits_total(
            [a.start for a, _ in accepted if policies[a.kind].mode != EffectMode.SUGERIR], c.start, cap
        ):
            dropped[c.kind] += 1
            continue
        asset: str | None = None
        if c.pool:
            asset = min(c.pool, key=lambda aid: (used[aid], aid))
            used[asset] += 1
        accepted.append((c, asset))
    for kind, n in sorted(dropped.items()):
        warnings.add(f"{kind.value}: {n} candidato(s) ficaram fora do orçamento por minuto")
    return accepted


def _music_items(
    moments: Sequence[Moment],
    policy: PolicyLike,
    assets: Sequence[AssetRef],
    preferred: Mapping[str, Sequence[str]],
    params: FinishParams,
    total: int,
    warnings: set[str],
) -> list[FinishItem]:
    tracks = {a.id: a for a in assets if a.kind == "musica" and a.bpm}
    used: Counter[str] = Counter()
    out: list[FinishItem] = []
    by_chapter: dict[int, list[Moment]] = {}
    for m in moments:
        by_chapter.setdefault(m.chapter, []).append(m)
    for chapter in sorted(by_chapter):
        ms = by_chapter[chapter]
        mood = chapter_mood(ms)
        pool = [t for t in preferred.get(mood, ()) if t in tracks]
        if not pool:
            pool = sorted(a.id for a in tracks.values() if a.mood == mood)
        if not pool:
            warnings.add(f"musica: nenhuma trilha para o clima '{mood}' (capítulo {chapter})")
            continue
        pick = min(pool, key=lambda tid: (used[tid], tid))
        start = min(m.start for m in ms)
        bpm = float(tracks[pick].bpm or 0)
        snapped = snap_music(min(max(m.end for m in ms), total) - start, bpm, params.min_bars_music)
        if snapped is None:
            warnings.add(f"musica: capítulo {chapter} curto demais para um compasso de '{pick}'")
            continue
        used[pick] += 1
        frames, bars = snapped
        out.append(
            FinishItem(
                f"musica-{chapter}",
                EffectKind.MUSICA,
                policy.mode,
                Track.A4,
                start,
                frames,
                1.0,
                chapter,
                f"capitulo-{chapter}",
                pick,
                {"bpm": bpm, "compassos": bars, "clima": mood},
                f"clima '{mood}' do capítulo {chapter}, corte em {bars} compassos",
            )
        )
    return out


SUGGEST_ONLY = frozenset({EffectKind.PIADA_VISUAL, EffectKind.FREEZE_TEXTO})
"""Efeitos que nada gera nem renderiza (só marcador): em `editavel`/`renderizado` ocupariam vaga do orçamento
sem aparecer no vídeo, então a política é rebaixada para `sugerir`, com aviso."""


@dataclass(frozen=True)
class _Policy:
    mode: EffectMode
    max_per_minute: float
    min_score: float


def _only_what_can_be_applied(
    policies: Mapping[EffectKind, PolicyLike], warnings: set[str]
) -> dict[EffectKind, PolicyLike]:
    out: dict[EffectKind, PolicyLike] = {}
    for kind, p in policies.items():
        if kind in SUGGEST_ONLY and p.mode != EffectMode.SUGERIR:
            warnings.add(f"{kind.value}: não há forma {p.mode.value} (só marcador); rebaixado para sugerir")
            p = _Policy(EffectMode.SUGERIR, p.max_per_minute, p.min_score)
        out[kind] = p
    return out


def build_finish_plan(
    moments: Sequence[Moment],
    policies: Mapping[EffectKind, PolicyLike],
    *,
    total_frames: int,
    max_total_per_minute: float = 6.0,
    cards: Sequence[CardRef] = (),
    assets: Sequence[AssetRef] = (),
    preferred_music: Mapping[str, Sequence[str]] | None = None,
    lut: str | None = None,
    params: FinishParams | None = None,
) -> FinishPlan:
    params = params or FinishParams()
    preferred = preferred_music or {}
    warnings: set[str] = set()
    policies = _only_what_can_be_applied(policies, warnings)
    plan = FinishPlan(
        input_hash=input_hash(
            PLAN_VERSION,
            sorted(moments, key=lambda m: (m.start, m.id)),
            sorted(cards, key=lambda c: (c.start, c.chapter)),
            dict(policies_view(policies)),
            sorted(assets, key=lambda a: a.id),
            {k: list(v) for k, v in preferred.items()},
            total_frames,
            max_total_per_minute,
            lut,
            params,
        )
    )
    candidates = _moment_candidates(moments, policies, assets, total_frames, params, warnings)
    for c, asset in _select(candidates, policies, max_total_per_minute, warnings):
        plan.items.append(
            FinishItem(
                f"{c.kind.value}-{c.start}",
                c.kind,
                policies[c.kind].mode,
                TRACK_OF[c.kind],
                c.start,
                c.frames,
                round(c.intensity, 3),
                c.moment.chapter,
                c.moment.id,
                asset,
                dict(c.params),
                c.reason,
            )
        )
    if (p := policies.get(EffectKind.CARTELA_DIA)) and p.max_per_minute > 0:
        for card in cards:
            plan.items.append(
                FinishItem(
                    f"cartela_dia-{card.start}",
                    EffectKind.CARTELA_DIA,
                    p.mode,
                    Track.V5,
                    card.start,
                    card.frames,
                    1.0,
                    card.chapter,
                    f"capitulo-{card.chapter}",
                    None,
                    {"numero_editavel": 1},
                    f"abertura do capítulo {card.chapter}",
                )
            )
    if (p := policies.get(EffectKind.MUSICA)) and p.max_per_minute > 0:
        plan.items.extend(_music_items(moments, p, assets, preferred, params, total_frames, warnings))
    if lut and (p := policies.get(EffectKind.COR_LUT)) and p.max_per_minute > 0 and total_frames > 0:
        plan.items.append(
            FinishItem(
                "cor_lut-0",
                EffectKind.COR_LUT,
                p.mode,
                Track.V1,
                0,
                total_frames,
                1.0,
                0,
                "",
                None,
                {"lut": lut},
                "LUT de série sobre a gameplay inteira",
            )
        )
    for kind in sorted(NOT_IN_8B, key=lambda k: k.value):
        if (p := policies.get(kind)) and p.max_per_minute > 0 and p.mode != EffectMode.SUGERIR:
            warnings.add(f"{kind.value}: não gerado (precisa dos dias do Studio ou das palavras do Whisper)")
    plan.items.sort(key=lambda i: (i.start, i.track.value, i.kind.value))
    plan.warnings = sorted(warnings)
    return plan


def policies_view(policies: Mapping[EffectKind, PolicyLike]) -> dict[str, tuple[str, float, float]]:
    """Forma canônica das políticas para o hash da entrada."""
    return {k.value: (p.mode.value, p.max_per_minute, p.min_score) for k, p in policies.items()}


EDITABLE_KINDS = frozenset(
    {
        EffectKind.ZOOM,
        EffectKind.SHAKE,
        EffectKind.CONTADOR_MORTES,
        EffectKind.SFX,
        EffectKind.SFX_MEME,
        EffectKind.MUSICA,
        EffectKind.COR_LUT,
    }
)
"""Efeitos que o FCPXML sabe levar como editáveis; os demais só existem como sugestão (marcador)."""

DECISIONS = frozenset({"aceito", "removido"})


def decision_key(item: FinishItem) -> str:
    """Chave da decisão do criador: o item **e o momento** a que ele pertence.

    O `id` do item é posicional (`zoom-1200`): se o plano mudar (outro alvo de duração, outra nota mínima), o
    mesmo `id` pode cair em outro trecho. Com o momento na chave, a decisão antiga deixa de valer em silêncio
    em vez de atingir um efeito que o criador nunca viu.
    """
    return f"{item.id}@{item.moment_id}"


def apply_decisions(plan: FinishPlan, decisions: Mapping[str, str]) -> FinishPlan:
    """Decisões do criador por `decision_key` (Studio, 8E): `removido` tira o item; `aceito` promove uma
    sugestão para `editavel` (o modo reversível). Não refaz o orçamento: tirar um item não libera vaga."""
    items: list[FinishItem] = []
    warnings = list(plan.warnings)
    for item in plan.items:
        decision = decisions.get(decision_key(item))
        if decision == "removido":
            continue
        if decision == "aceito" and item.mode == EffectMode.SUGERIR:
            if item.kind in EDITABLE_KINDS:
                item = replace(item, mode=EffectMode.EDITAVEL)
            else:
                warnings.append(f"{item.id}: {item.kind.value} não tem forma editável; segue como marcador")
        items.append(item)
    return FinishPlan(items, sorted(set(warnings)), plan.input_hash)

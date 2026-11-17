"""Biblioteca de B-roll (Fase 3B): candidatos, utilidade, tags e busca por texto sobre os embeddings.

Candidato = trecho de câmera parada ou panorâmica fora de menu/loading/pausa. A nota de utilidade é zero-shot
(cena de jogo contra menu, inventário, tela preta e loading). Não mede beleza: cena escura ou
medonha vale tanto quanto uma paisagem; o que casa com a narração é a busca por texto.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from cronista.domain.evidence import AnalysisEvent
from cronista.video.ports import FrameEmbedder

FloatArray = npt.NDArray[np.float32]

POSITIVE = (
    "a game scene showing an environment",
    "a first person view of a game world",
    "a dark scary cave in a video game",
    "a landscape in a video game",
)
NEGATIVE = (
    "a menu screen full of text",
    "an inventory screen",
    "a black screen",
    "a loading screen",
)
VOCAB = (
    "a cave",
    "a forest",
    "a mountain",
    "a lake or river",
    "the ocean or beach",
    "a desert",
    "a snowy landscape",
    "a village or town",
    "a house or base",
    "a night sky",
    "a sunset or sunrise",
    "a dark underground tunnel",
    "a field of crops",
)
BLOCKED = frozenset({"menu", "loading", "pausa", "idle"})


@dataclass(frozen=True)
class BrollParams:
    min_seconds: float = 4.0
    max_overlap: float = 0.3
    """Fração do trecho coberta por menu/loading/pausa/idle acima da qual ele deixa de ser candidato."""
    temperature: float = 100.0
    top_tags: int = 3


@dataclass(frozen=True)
class Candidate:
    start_frame: int
    end_frame: int
    movement: str
    confidence: float


def candidates(events: Sequence[AnalysisEvent], params: BrollParams, fps: int = 60) -> list[Candidate]:
    blocked = [(e.evidence.start_frame, e.evidence.end_frame) for e in events if e.kind in BLOCKED]
    out: list[Candidate] = []
    for e in events:
        tipo = str(e.payload.get("tipo", ""))
        if e.kind != "movimento_camera" or tipo not in ("parada", "panoramica"):
            continue
        a, b = e.evidence.start_frame, e.evidence.end_frame
        if (b - a) < params.min_seconds * fps:
            continue
        covered = sum(max(0, min(b, y) - max(a, x)) for x, y in blocked)
        if covered > params.max_overlap * (b - a):
            continue
        out.append(Candidate(a, b, tipo, e.evidence.confidence))
    return out


def _unit(x: FloatArray) -> FloatArray:
    return (x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), 1e-9)).astype(np.float32)


def beauty(emb: FloatArray, pos: FloatArray, neg: FloatArray, temperature: float) -> FloatArray:
    """Probabilidade (0 a 1) por quadro de parecer mais com os prompts positivos que com os negativos."""
    p = (emb @ pos.T).max(axis=1)
    n = (emb @ neg.T).max(axis=1)
    return (1.0 / (1.0 + np.exp(-temperature * (p - n)))).astype(np.float32)


def score_candidate(
    emb: FloatArray, embedder: FrameEmbedder, params: BrollParams, *, hop: int, c: Candidate
) -> dict[str, Any] | None:
    """Nota, tags e quadro de capa do trecho; `None` se não há embedding dentro dele."""
    first, last = c.start_frame // hop, max(c.end_frame // hop, c.start_frame // hop + 1)
    seg = emb[first:last]
    if len(seg) == 0:
        return None
    pos, neg = _unit(embedder.embed_text(POSITIVE)), _unit(embedder.embed_text(NEGATIVE))
    per = beauty(seg, pos, neg, params.temperature)
    vocab = _unit(embedder.embed_text([f"a photo of {v}" for v in VOCAB]))
    sims = _unit(seg.mean(axis=0, keepdims=True))[0] @ vocab.T
    order = np.argsort(-sims)[: params.top_tags]
    return {
        "movimento": c.movement,
        "utilidade": float(per.mean()),
        "tags": [VOCAB[int(i)] for i in order],
        "cover_frame": int((first + int(np.argmax(per))) * hop),
    }


def search(
    emb: FloatArray,
    embedder: FrameEmbedder,
    events: Sequence[AnalysisEvent],
    query: str,
    *,
    hop: int,
    top: int = 5,
) -> list[tuple[AnalysisEvent, float]]:
    """B-roll mais parecido com o texto (cosseno médio do trecho com a consulta), do melhor para o pior."""
    q = _unit(embedder.embed_text([query]))[0]
    scored: list[tuple[AnalysisEvent, float]] = []
    for e in events:
        if e.kind != "broll":
            continue
        seg = emb[
            e.evidence.start_frame // hop : max(
                e.evidence.end_frame // hop, e.evidence.start_frame // hop + 1
            )
        ]
        if len(seg):
            scored.append((e, float(_unit(seg.mean(axis=0, keepdims=True))[0] @ q)))
    return sorted(scored, key=lambda t: -t[1])[:top]

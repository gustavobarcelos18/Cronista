"""Contextos visuais por sessão (Fase 3B): agrupa quadros parecidos pelos embeddings, sem nome por jogo.

Decisão (a registrar no histórico): agrupamento incremental por similaridade de cosseno com limiar (algoritmo
"líder" com centróide móvel), seguido de filtro de mediana nos rótulos e de poda de contextos curtos. É
determinístico, linear no tempo, não precisa do número de grupos e roda em CPU; HDBSCAN fica como alternativa
se a conferência de olho na sessão real mostrar contextos instáveis.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

NO_CONTEXT = -1

Labels = npt.NDArray[np.int32]
Matrix = npt.NDArray[np.float32]


@dataclass(frozen=True)
class ContextParams:
    threshold: float = 0.85
    """Cosseno mínimo com o centróide para o quadro entrar no grupo; abaixo disso abre um grupo novo."""
    smooth: int = 5
    """Janela (amostras) do filtro de mediana nos rótulos: tira piscadas de 1 a 2 quadros."""
    min_seconds: float = 20.0
    """Contexto com menos tempo total que isto vira `NO_CONTEXT` (e cai na linha de base da sessão)."""


@dataclass(frozen=True)
class Context:
    id: int
    seconds: float
    representative: int
    """Índice da amostra mais próxima do centróide (vira o quadro de capa)."""


@dataclass(frozen=True)
class ContextResult:
    labels: Labels
    contexts: list[Context]
    centroids: Matrix


def _leader(emb: Matrix, threshold: float) -> tuple[Labels, Matrix]:
    n = len(emb)
    labels = np.empty(n, dtype=np.int32)
    sums: list[npt.NDArray[np.float64]] = []
    counts: list[int] = []
    unit: list[npt.NDArray[np.float64]] = []
    for i in range(n):
        vec = emb[i].astype(np.float64)
        best, best_sim = -1, -2.0
        if unit:
            sims = np.stack(unit) @ vec
            best = int(np.argmax(sims))
            best_sim = float(sims[best])
        if best >= 0 and best_sim >= threshold:
            labels[i] = best
            sums[best] += vec
            counts[best] += 1
            norm = np.linalg.norm(sums[best])
            unit[best] = sums[best] / norm if norm > 0 else sums[best]
        else:
            labels[i] = len(unit)
            sums.append(vec.copy())
            counts.append(1)
            norm = np.linalg.norm(vec)
            unit.append(vec / norm if norm > 0 else vec)
    centroids = np.stack(unit).astype(np.float32) if unit else np.zeros((0, emb.shape[1]), np.float32)
    return labels, centroids


def _median_filter(labels: Labels, window: int) -> Labels:
    if window <= 1 or len(labels) == 0:
        return labels
    half = window // 2
    out = labels.copy()
    padded = np.pad(labels, half, mode="edge")
    for i in range(len(labels)):
        values, counts = np.unique(padded[i : i + 2 * half + 1], return_counts=True)
        out[i] = values[np.argmax(counts)]  # moda: rótulos não têm ordem, então a mediana vira voto
    return out


def cluster(embeddings: Matrix, sample_seconds: float, params: ContextParams | None = None) -> ContextResult:
    """Rótulo de contexto por amostra (`NO_CONTEXT` se curto), numerado por ordem de aparição."""
    p = params or ContextParams()
    if len(embeddings) == 0:
        return ContextResult(np.zeros(0, np.int32), [], np.zeros((0, embeddings.shape[-1]), np.float32))
    raw, _ = _leader(embeddings, p.threshold)
    labels = _median_filter(raw, p.smooth)
    kept: list[int] = []
    for old in dict.fromkeys(labels.tolist()):  # ordem de aparição
        if int(np.sum(labels == old)) * sample_seconds >= p.min_seconds:
            kept.append(old)
    remap = {old: new for new, old in enumerate(kept)}
    final = np.array([remap.get(int(x), NO_CONTEXT) for x in labels], dtype=np.int32)
    contexts: list[Context] = []
    new_centroids: list[npt.NDArray[np.float32]] = []
    for new in range(len(remap)):
        members = np.flatnonzero(final == new)
        centroid = embeddings[members].astype(np.float64).mean(axis=0)
        norm = np.linalg.norm(centroid)
        centroid = centroid / norm if norm > 0 else centroid
        sims = embeddings[members] @ centroid.astype(np.float32)
        contexts.append(
            Context(
                id=new, seconds=len(members) * sample_seconds, representative=int(members[np.argmax(sims)])
            )
        )
        new_centroids.append(centroid.astype(np.float32))
    matrix = np.stack(new_centroids) if new_centroids else np.zeros((0, embeddings.shape[1]), np.float32)
    return ContextResult(final, contexts, matrix)


def runs(labels: Labels) -> list[tuple[int, int, int]]:
    """Trechos contínuos `(início, fim_exclusivo, rótulo)` de cada rótulo."""
    out: list[tuple[int, int, int]] = []
    start = 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[start]:
            out.append((start, i, int(labels[start])))
            start = i
    return out

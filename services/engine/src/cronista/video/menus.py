"""Tipos de menu (Fase 3B): menus parecidos agrupados por embedding, sem nome e sem regra por jogo.

A heurística da 3A diz só "tela de interface parada". Aqui cada menu vira um vetor (média dos embeddings)
e os parecidos formam um **tipo** numerado. Dar nome ao tipo (configuração, inventário, diálogo, mapa) é uma
pergunta por grupo, não por menu: fica com o VLM (3C) ou com o criador. O peso de cada tipo é da Fase 4.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from cronista.audio.events import EVENTS_KEY, events_from_result, write_events_file
from cronista.config import Settings
from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource, params_hash
from cronista.domain.models import StageResult
from cronista.pipeline.stage import StageContext
from cronista.video.context_stages import EMBED_HOP, load_embeddings

FloatArray = npt.NDArray[np.float32]


@dataclass(frozen=True)
class MenuParams:
    similarity: float = 0.3
    """Cosseno mínimo do menu com o centróide do tipo, depois de subtrair a média de todos os menus."""
    similarity_raw: float = 0.93
    """Limiar para poucos menus, quando não dá para centrar (o fundo escuro comum deixa tudo acima de 0,8)."""
    min_menus_to_center: int = 4


def group(vectors: FloatArray, params: MenuParams) -> tuple[npt.NDArray[np.int32], FloatArray]:
    """Agrupamento "líder": rótulo de cada vetor e centróides normalizados, na ordem do tempo."""
    labels = np.zeros(len(vectors), np.int32)
    sums: list[FloatArray] = []
    counts: list[int] = []
    cents: list[FloatArray] = []
    for i, v in enumerate(vectors):
        best, best_sim = -1, params.similarity
        for k, c in enumerate(cents):
            sim = float(v @ c)
            if sim >= best_sim:
                best, best_sim = k, sim
        if best < 0:
            sums.append(v.copy())
            counts.append(1)
            cents.append(v.copy())
            best = len(cents) - 1
        else:
            sums[best] += v
            counts[best] += 1
            cents[best] = sums[best] / max(float(np.linalg.norm(sums[best])), 1e-9)
        labels[i] = best
    return labels, (
        np.stack(cents) if cents else np.zeros((0, vectors.shape[1] if vectors.ndim == 2 else 0), np.float32)
    )


class MenuTypesStage:
    """Eventos `menu_tipo`: um por menu da 3A, com o id do tipo e um menu representativo."""

    name = "video_menu_types"
    version = "2"
    needs: tuple[str, ...] = ("video_scenes", "video_embeddings")
    uses_gpu = False

    def __init__(self, params: MenuParams | None = None) -> None:
        self.menu = params or MenuParams()

    def params(self, settings: Settings) -> dict[str, Any]:
        return dict(self.menu.__dict__)

    def run(self, ctx: StageContext) -> StageResult:
        emb = np.asarray(load_embeddings(ctx.inputs["video_embeddings"]), dtype=np.float32)
        menus = [e for e in events_from_result(ctx.inputs["video_scenes"]) or [] if e.kind == "menu"]
        rows: list[tuple[AnalysisEvent, FloatArray]] = []
        for m in menus:
            first = m.evidence.start_frame // EMBED_HOP
            seg = emb[first : max(m.evidence.end_frame // EMBED_HOP, first + 1)]
            if len(seg):
                v = seg.mean(axis=0)
                rows.append((m, (v / max(float(np.linalg.norm(v)), 1e-9)).astype(np.float32)))
        if not rows:
            path = write_events_file(ctx.out_dir, [])
            return StageResult(files=[path], data={EVENTS_KEY: path, "count": 0, "types": []})
        vectors = np.stack([v for _, v in rows])
        if len(vectors) >= self.menu.min_menus_to_center:
            # menus têm muito em comum (fundo escuro, painéis): sem tirar a média, tudo parece o mesmo tipo
            vectors = vectors - vectors.mean(axis=0)
            vectors = (vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9)).astype(
                np.float32
            )
        centered = len(vectors) >= self.menu.min_menus_to_center
        limit = self.menu.similarity if centered else self.menu.similarity_raw
        labels, cents = group(vectors, MenuParams(similarity=limit))
        digest = params_hash(self.params(ctx.settings))
        events: list[AnalysisEvent] = []
        types: list[dict[str, Any]] = []
        for tid in range(len(cents)):
            idx = np.flatnonzero(labels == tid)
            rep = int(idx[int(np.argmax(vectors[idx] @ cents[tid]))])
            rep_frame = rows[rep][0].evidence.start_frame
            seconds = sum((rows[i][0].evidence.end_frame - rows[i][0].evidence.start_frame) / 60 for i in idx)
            types.append(
                {"id": tid, "menus": len(idx), "seconds": seconds, "representative_frame": rep_frame}
            )
            for i in idx:
                m = rows[i][0]
                events.append(
                    AnalysisEvent(
                        kind="menu_tipo",
                        evidence=Evidence(
                            source=EvidenceSource.CENA,
                            start_frame=m.evidence.start_frame,
                            end_frame=m.evidence.end_frame,
                            confidence=float(np.clip(vectors[i] @ cents[tid], 0.0, 1.0)),
                            model="video-menus",
                            model_version=self.version,
                            params_hash=digest,
                        ),
                        payload={
                            "tipo_id": tid,
                            "menus_no_tipo": len(idx),
                            "representative_frame": rep_frame,
                        },
                    )
                )
        events.sort(key=lambda e: e.evidence.start_frame)
        path = write_events_file(ctx.out_dir, events)
        return StageResult(files=[path], data={EVENTS_KEY: path, "count": len(events), "types": types})

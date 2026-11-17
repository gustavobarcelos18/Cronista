"""Heurística universal de estado de tela e movimento de câmera (Fase 3A).

Sem rótulo por jogo: só o comportamento dos sinais visuais. Os limiares são pontos de partida a calibrar na 3C
contra o gabarito (nenhum é por jogo). `pausa` (menu com o fundo escurecido) fica para a 3B, com embeddings.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

BoolArray = npt.NDArray[np.bool_]
FloatArray = npt.NDArray[np.float32]


@dataclass(frozen=True)
class ScreenParams:
    sample_fps: int = 5
    dark_luma: float = 0.10  # luminância média abaixo disso é tela escura
    dark_motion: float = 0.01
    loading_min_s: float = 2.0
    still_min: float = 0.90  # fração de pixels parados para a tela contar como estática
    menu_edge: float = 0.12  # densidade de bordas de uma tela de menu (texto, caixas)
    menu_min_s: float = 3.0
    idle_min_s: float = 5.0
    pan_shift_px: float = 1.5  # deslocamento global (em px de 160x90) de uma panorâmica
    pan_conf: float = 0.15
    still_shift_px: float = 0.5
    camera_min_s: float = 2.0
    cut_hist: float = 0.5  # distância de histograma de um corte de cena
    merge_gap_s: float = 0.6  # lacunas menores que isso não quebram um trecho


@dataclass(frozen=True)
class ScreenSpan:
    kind: str
    start: int  # índice da primeira amostra
    end: int  # índice depois da última amostra
    confidence: float
    payload: dict[str, float | str]


def _runs(mask: BoolArray, min_len: int, max_gap: int) -> list[tuple[int, int]]:
    """Trechos de `True` (lacunas de até `max_gap` amostras não quebram) com pelo menos `min_len` amostras."""
    idx = np.flatnonzero(mask)
    runs: list[list[int]] = []
    for i in idx:
        if runs and i - runs[-1][1] <= max_gap + 1:
            runs[-1][1] = int(i)
        else:
            runs.append([int(i), int(i)])
    return [(a, b + 1) for a, b in runs if b + 1 - a >= min_len]


def detect(signals: Mapping[str, FloatArray], params: ScreenParams) -> list[ScreenSpan]:
    """Eventos de tela a partir dos sinais (um array por nome, todos do mesmo tamanho)."""
    motion, still = signals["motion"], signals["still"]
    luma, edge = signals["luma_mean"], signals["edge_density"]
    shift, conf = signals["shift"], signals["shift_conf"]
    hist = signals["hist_diff"]
    fps = params.sample_fps
    gap = max(round(params.merge_gap_s * fps), 0)

    def mean(arr: FloatArray, a: int, b: int) -> float:
        return float(arr[a:b].mean())

    out: list[ScreenSpan] = []

    dark = (luma < params.dark_luma) & (motion < params.dark_motion)
    for a, b in _runs(dark, round(params.loading_min_s * fps), gap):
        out.append(
            ScreenSpan("loading", a, b, 0.9, {"luma_mean": mean(luma, a, b), "motivo": "tela escura parada"})
        )

    static = still >= params.still_min
    menu = static & (edge >= params.menu_edge) & ~dark
    for a, b in _runs(menu, round(params.menu_min_s * fps), gap):
        out.append(
            ScreenSpan("menu", a, b, 0.7, {"edge_density": mean(edge, a, b), "still": mean(still, a, b)})
        )
    idle = static & (edge < params.menu_edge) & ~dark
    for a, b in _runs(idle, round(params.idle_min_s * fps), gap):
        out.append(
            ScreenSpan("idle", a, b, 0.6, {"edge_density": mean(edge, a, b), "still": mean(still, a, b)})
        )

    camera_len = round(params.camera_min_s * fps)
    panning = (shift >= params.pan_shift_px) & (conf >= params.pan_conf) & ~static & ~dark
    for a, b in _runs(panning, camera_len, gap):
        out.append(
            ScreenSpan("movimento_camera", a, b, 0.6, {"tipo": "panoramica", "shift_px": mean(shift, a, b)})
        )
    held = (shift < params.still_shift_px) & (motion < 0.02) & ~dark
    for a, b in _runs(held, camera_len, gap):
        out.append(
            ScreenSpan("movimento_camera", a, b, 0.6, {"tipo": "parada", "shift_px": mean(shift, a, b)})
        )

    cuts = np.flatnonzero(hist >= params.cut_hist)
    for i in cuts:
        if i > 0:
            out.append(
                ScreenSpan(
                    "cena", int(i), int(i) + 1, float(min(hist[i] * 1.5, 1.0)), {"hist_diff": float(hist[i])}
                )
            )
    return sorted(out, key=lambda s: (s.start, s.kind))

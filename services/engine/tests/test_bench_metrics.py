"""Métricas dos benchmarks (3B): funções puras, sem modelo nem GPU."""

from __future__ import annotations

import numpy as np

from cronista.video.bench import knn_accuracy, labeled_seconds, zeroshot_accuracy
from cronista.video.bench_vision import cer, day_time, hud_metrics, parse_screen, screen_metrics


def test_cer_e_dia_hora() -> None:
    assert cer("Day 1, 10:14", "day 1 10:14") == 0.0
    assert cer("Dark Forest", "Dark Forst") > 0.0
    assert day_time("Kingdom of Vaaz Day 2, 06:05") == (2, 6, 5)
    assert day_time("sem dia nenhum") is None


def test_metricas_de_hud_e_tela() -> None:
    truth = {1: "Day 1, 10:14", 2: "Day 2, 06:05"}
    good, mean_cer, day_ok = hud_metrics(truth, {1: "Day 1, 10:14", 2: "Day 2, 06:06"})
    assert good == 1.0 and 0.0 < mean_cer < 0.1 and day_ok == 0.5
    assert parse_screen("The answer is: Menu.") == "menu"
    assert parse_screen("banana") is None
    acc, invalid, per_class = screen_metrics({1: "menu", 2: "gameplay"}, {1: "menu", 2: "não sei"})
    assert acc == 0.5 and invalid == 1 and per_class == {"menu": 1.0, "gameplay": 0.0}


def test_knn_ignora_vizinhos_no_tempo_e_zeroshot() -> None:
    rng = np.random.default_rng(0)
    a, b = np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])
    emb = np.stack([(a if i < 40 else b) + rng.normal(0, 0.02, 3) for i in range(80)]).astype(np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)
    idx, labels = labeled_seconds([(0.0, 40.0, "a"), (40.0, 80.0, "b")], len(emb))
    assert len(idx) == 80 and knn_accuracy(emb, idx, labels) == 1.0
    text = np.stack([a, b]).astype(np.float32)
    assert zeroshot_accuracy(emb, idx, labels, text, ["a", "b"]) == 1.0

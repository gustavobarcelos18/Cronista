"""Benchmark dos modelos de embedding de quadro (3B): velocidade, VRAM e qualidade em gabarito pequeno.

Desempenho: a decodificação do proxy fica de fora da medida (igual para todos); mede só o modelo, depois de um
aquecimento que carrega os pesos. Qualidade (opcional): um CSV `inicio_s,fim_s,rotulo` com trechos de contexto
conhecidos; mede acerto de k-vizinhos (ignorando vizinhos próximos no tempo, quase o mesmo quadro) e de
"zero-shot" pelo texto do rótulo. Com gabarito pequeno e rótulos vindos de outro modelo, o número
de qualidade é só um indício; a decisão pesa mais o desempenho e a conferência de olho.
"""

from __future__ import annotations

import csv
import gc
import importlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from cronista.audio.bench import _Peak
from cronista.config import Settings
from cronista.video import frames as vframes
from cronista.video.ports import FrameEmbedder

Truth = list[tuple[float, float, str]]
Matrix = npt.NDArray[np.float32]

KNN_K = 5
KNN_GAP_S = 10


@dataclass
class VideoBenchRow:
    model: str
    video_s: float
    wall_s: float
    warmup_s: float  # primeira chamada: inclui download e carga do modelo
    speed_x: float  # segundos de vídeo por segundo de relógio, a 1 quadro por segundo
    vram_peak_mib: int | None
    dim: int
    knn_acc: float | None = None
    zeroshot_acc: float | None = None
    note: str = ""

    @property
    def hours_per_10h(self) -> float:
        return 10.0 / self.speed_x if self.speed_x else float("inf")


def load_truth(path: Path) -> Truth:
    with path.open(encoding="utf-8", newline="") as handle:
        return [
            (float(r["inicio_s"]), float(r["fim_s"]), r["rotulo"].strip()) for r in csv.DictReader(handle)
        ]


def labeled_seconds(truth: Truth, n: int) -> tuple[npt.NDArray[np.intp], list[str]]:
    """Índices (segundos) dentro do vídeo com rótulo, e o rótulo de cada um."""
    idx: list[int] = []
    labels: list[str] = []
    for start, end, label in truth:
        for sec in range(int(start), min(int(end), n)):
            idx.append(sec)
            labels.append(label)
    return np.asarray(idx, dtype=np.intp), labels


def knn_accuracy(
    emb: Matrix, idx: npt.NDArray[np.intp], labels: list[str], k: int = KNN_K, gap: int = KNN_GAP_S
) -> float:
    """Acerto de k-vizinhos entre os quadros rotulados, sem olhar quadros a menos de `gap` s (no tempo)."""
    if len(idx) < 2:
        return 0.0
    x = emb[idx]
    sims = x @ x.T
    far = np.abs(idx[:, None] - idx[None, :]) > gap
    sims = np.where(far, sims, -np.inf)
    y = np.asarray(labels)
    hits = 0
    for i in range(len(idx)):
        order = np.argsort(sims[i])[::-1][:k]
        order = order[np.isfinite(sims[i][order])]
        if len(order) == 0:
            continue
        values, counts = np.unique(y[order], return_counts=True)
        hits += int(values[np.argmax(counts)] == y[i])
    return hits / len(idx)


def zeroshot_accuracy(
    emb: Matrix, idx: npt.NDArray[np.intp], labels: list[str], text: Matrix, names: list[str]
) -> float:
    """Acerto escolhendo o rótulo cujo texto está mais perto do quadro."""
    if len(idx) == 0:
        return 0.0
    pred = np.argmax(emb[idx] @ text.T, axis=1)
    return float(np.mean([names[p] == label for p, label in zip(pred, labels, strict=True)]))


def decode_all(settings: Settings, proxy: Path, size: int) -> Any:
    return np.concatenate(list(vframes.iter_rgb_blocks(settings, proxy, sample_fps=1, size=size, block=256)))


def free_gpu() -> None:
    gc.collect()
    try:
        torch: Any = importlib.import_module("torch")
        torch.cuda.empty_cache()
    except ImportError:
        pass


def run_one(
    name: str,
    embedder: FrameEmbedder,
    frames: Any,
    truth: Truth | None,
    template: str,
) -> tuple[VideoBenchRow, Matrix]:
    with _Peak() as peak:
        t0 = time.monotonic()
        embedder.embed_images(frames[:8], pause=lambda: None)
        warmup = time.monotonic() - t0
        t1 = time.monotonic()
        emb = embedder.embed_images(frames, pause=lambda: None)
        wall = time.monotonic() - t1
    row = VideoBenchRow(
        model=name,
        video_s=float(len(frames)),
        wall_s=round(wall, 2),
        warmup_s=round(warmup, 1),
        speed_x=round(len(frames) / wall, 1) if wall > 0 else 0.0,
        vram_peak_mib=peak.vram_mib,
        dim=int(emb.shape[1]),
    )
    if truth:
        idx, labels = labeled_seconds(truth, len(emb))
        row.knn_acc = round(knn_accuracy(emb, idx, labels), 3)
        names = sorted(set(labels))
        try:
            text = embedder.embed_text([template.format(n) for n in names])
            row.zeroshot_acc = round(zeroshot_accuracy(emb, idx, labels, text, names), 3)
        except Exception as exc:  # tokenizer ausente etc.: o resto da medida continua valendo
            row.note = f"zero-shot indisponível: {exc}"[:200]
    return row, emb


def run_bench(
    settings: Settings,
    proxy: Path,
    candidates: Mapping[str, Callable[[], FrameEmbedder]],
    truth: Truth | None,
    template: str = "a screenshot of a video game: {}",
    save_dir: Path | None = None,
    progress: Callable[[list[VideoBenchRow]], None] | None = None,
) -> list[VideoBenchRow]:
    rows: list[VideoBenchRow] = []
    decoded: dict[int, Any] = {}
    for name, make in candidates.items():
        embedder: FrameEmbedder | None = None
        try:
            embedder = make()
            if embedder.input_size not in decoded:
                decoded[embedder.input_size] = decode_all(settings, proxy, embedder.input_size)
            row, emb = run_one(name, embedder, decoded[embedder.input_size], truth, template)
            if save_dir is not None:
                save_dir.mkdir(parents=True, exist_ok=True)
                np.save(save_dir / f"{name}.npy", emb.astype(np.float16))
            rows.append(row)
        except Exception as exc:  # download recusado, VRAM estourada, nome de checkpoint errado
            rows.append(VideoBenchRow(name, 0.0, 0.0, 0.0, 0.0, None, 0, note=f"falhou: {exc}"[:300]))
        finally:
            del embedder
            free_gpu()
            if progress is not None:
                progress(rows)  # grava a cada modelo: matar a execução não perde o que já foi medido
    return rows


def render_table(rows: list[VideoBenchRow]) -> str:
    cols = f"{'modelo':<22}{'dim':>6}{'x tempo real':>14}{'10 h em':>10}{'VRAM MiB':>10}{'kNN':>7}"
    head = cols + f"{'zero-shot':>10}"
    lines = [head, "-" * len(head)]
    for r in rows:
        if r.speed_x == 0:
            lines.append(f"{r.model:<22}  {r.note}")
            continue
        vram = r.vram_peak_mib if r.vram_peak_mib is not None else "?"
        knn = "-" if r.knn_acc is None else f"{r.knn_acc:.2f}"
        zs = "-" if r.zeroshot_acc is None else f"{r.zeroshot_acc:.2f}"
        lines.append(
            f"{r.model:<22}{r.dim:>6}{r.speed_x:>14.1f}{r.hours_per_10h:>9.2f}h{vram:>10}{knn:>7}{zs:>11}"
        )
        if r.note:
            lines.append(f"    {r.note}")
    return "\n".join(lines)


def write_results(rows: list[VideoBenchRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(r) for r in rows], indent=2, ensure_ascii=False), encoding="utf-8")

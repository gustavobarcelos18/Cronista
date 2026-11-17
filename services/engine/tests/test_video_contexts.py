"""Contextos visuais e `novelty_ctx` (Fase 3B), com embeddings sintéticos e o embedder falso."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import numpy.typing as npt

from cronista.audio.events import events_from_result
from cronista.audio.signals import SIGNALS_KEY, load_signal, signal_metas, write_signal
from cronista.config import Settings
from cronista.devtools.synthetic_video import build, write_video
from cronista.domain.models import StageResult
from cronista.pipeline import StageContext
from cronista.video.context_stages import ContextNoveltyStage, ContextsStage, EmbeddingsStage
from cronista.video.contexts import NO_CONTEXT, ContextParams, cluster
from cronista.video.ports import VideoModels
from cronista.video.stages import video_stages
from tests.conftest import needs_ffmpeg
from tests.fakes_video import FakeEmbedder


def _blobs(seed: int = 1) -> tuple[npt.NDArray[np.float32], list[int]]:
    rng = np.random.default_rng(seed)
    centers = np.eye(8, dtype=np.float32)[[0, 1, 2]]
    plan = [0] * 60 + [1] * 50 + [0] * 40 + [2] * 3 + [1] * 50  # 3 s do contexto 2: curto demais
    rows = [centers[c] + rng.normal(0, 0.05, 8).astype(np.float32) for c in plan]
    emb = np.stack(rows)
    return (emb / np.linalg.norm(emb, axis=1, keepdims=True)).astype(np.float32), plan


def test_agrupa_por_semelhanca_e_poda_contexto_curto() -> None:
    emb, plan = _blobs()
    result = cluster(emb, 1.0, ContextParams(min_seconds=20))
    assert len(result.contexts) == 2
    labels = result.labels
    assert labels[0] == labels[120] == 0 and labels[65] == labels[190] == 1  # volta ao mesmo grupo
    short = plan.index(2)
    assert set(labels[short : short + 3].tolist()) <= {NO_CONTEXT, 0, 1}
    assert result.contexts[0].seconds > 90


def test_sem_embeddings_nao_quebra() -> None:
    result = cluster(np.zeros((0, 8), np.float32), 1.0)
    assert result.contexts == [] and len(result.labels) == 0


@needs_ffmpeg
def test_etapas_embeddings_contextos_e_novelty_ctx(tmp_path: Path, settings: Settings) -> None:
    frames, _ = build()
    proxy = tmp_path / "proxy.mp4"
    write_video(settings, proxy, frames)

    def ctx(name: str, inputs: dict[str, StageResult]) -> StageContext:
        out = tmp_path / name
        out.mkdir()
        return StageContext(media_path=proxy, out_dir=out, settings=settings, inputs=inputs)

    emb = EmbeddingsStage(FakeEmbedder()).run(ctx("emb", {"proxy": StageResult(data={"proxy": str(proxy)})}))
    arr = np.load(emb.data["embeddings"]["path"])
    assert arr.dtype == np.float16 and arr.shape[1] == 48

    contexts = ContextsStage(ContextParams(min_seconds=3)).run(ctx("ctx", {"video_embeddings": emb}))
    events = events_from_result(contexts) or []
    assert events and all(e.kind == "contexto" for e in events)
    assert all(e.evidence.start_frame % 60 == 0 for e in events)  # grade de 1 s em quadros a 60 fps

    # áudio sintético: o "onset" sobe no 2º contexto; a novidade da sessão o marca, a do contexto não
    n = len(arr) * 10  # amostras a 10 Hz
    onset = np.full(n, 1.0, np.float32)
    onset[n // 2 :] = 5.0
    aud = tmp_path / "aud"
    aud.mkdir()
    metas = {
        name: write_signal(aud, name, onset, unit="dB", source_track="game", version="1", params={})
        for name in ("game.onset", "game.novelty")
    }
    audio = StageResult(data={SIGNALS_KEY: {k: v.model_dump() for k, v in metas.items()}})
    labels = np.zeros(len(arr), np.float32)
    labels[len(arr) // 2 :] = 1
    vid = tmp_path / "vid"
    vid.mkdir()
    vmeta = write_signal(
        vid, "video.context", labels, unit="id", source_track="video", version="1", params={}, hop_frames=60
    )
    video = StageResult(data={SIGNALS_KEY: {"video.context": vmeta.model_dump()}})
    done = ContextNoveltyStage(min_context_s=10).run(
        ctx("nov", {"audio_signals": audio, "video_contexts": video})
    )
    novelty_ctx = load_signal(signal_metas(done)["game.novelty_ctx"]).values
    assert (
        len(novelty_ctx) == n and float(np.max(novelty_ctx)) < 1.0
    )  # patamar alto vira "normal" no contexto


def test_so_com_embedder_entram_as_etapas_de_3b() -> None:
    assert [s.name for s in video_stages()] == ["video_signals", "video_scenes"]
    models = VideoModels(embedder=FakeEmbedder())
    assert [s.name for s in video_stages(models)][-3:] == [
        "video_embeddings",
        "video_contexts",
        "context_novelty",
    ]
    assert "context_novelty" not in [s.name for s in video_stages(models, with_audio=False)]

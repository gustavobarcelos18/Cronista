"""Análise visual (Fase 3A): sinais e heurística de estado de tela, com vídeo sintético e verdade de campo."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from cronista.config import Settings
from cronista.devtools.synthetic_video import Truth, build, write_video
from cronista.domain.models import StageResult
from cronista.pipeline import StageContext
from cronista.video import frames as vframes
from cronista.video.screen_state import ScreenParams, detect
from cronista.video.signals import SIGNAL_NAMES, SignalParams, block_signals
from cronista.video.stages import VideoScenesStage, VideoSignalsStage
from tests.conftest import needs_ffmpeg


def _signals(frames: np.ndarray, block: int) -> dict[str, np.ndarray]:
    chunks: dict[str, list[np.ndarray]] = {name: [] for name in SIGNAL_NAMES}
    previous = None
    for start in range(0, len(frames), block):
        # reduz o quadro sintético (320x180) ao tamanho de análise por amostragem simples
        part = frames[start : start + block, ::2, ::2]
        result = block_signals(part, previous, SignalParams())
        previous = (result.last_frame, result.last_hist)
        for name in SIGNAL_NAMES:
            chunks[name].append(result.values[name])
    return {name: np.concatenate(parts) for name, parts in chunks.items()}


def _overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def _covers(spans: list[tuple[float, float]], truth: Truth, ratio: float = 0.8) -> bool:
    length = truth.end_s - truth.start_s
    return sum(_overlap(s, (truth.start_s, truth.end_s)) for s in spans) >= ratio * length


def test_continuidade_entre_blocos_nao_muda_os_sinais() -> None:
    frames, _ = build()
    whole = _signals(frames, len(frames))
    chunked = _signals(frames, 13)
    for name in SIGNAL_NAMES:
        assert np.allclose(whole[name], chunked[name], atol=1e-5), name


def test_detecta_loading_menu_idle_e_nao_confunde_jogabilidade() -> None:
    frames, truth = build()
    spans = detect(_signals(frames, 40), ScreenParams())
    by_kind: dict[str, list[tuple[float, float]]] = {}
    for sp in spans:
        by_kind.setdefault(sp.kind, []).append((sp.start / 5, sp.end / 5))
    for item in truth:
        if item.kind in ("loading", "menu", "idle"):
            assert _covers(by_kind.get(item.kind, []), item), f"{item.kind} não detectado: {by_kind}"
    # nenhum loading/menu/idle dentro da jogabilidade
    for item in truth:
        if item.kind == "gameplay":
            for kind in ("loading", "menu", "idle"):
                assert not any(
                    _overlap(s, (item.start_s, item.end_s)) > 0.5 for s in by_kind.get(kind, [])
                ), f"falso {kind} em jogabilidade"
    # jogabilidade deslizando é panorâmica
    assert any(sp.kind == "movimento_camera" and sp.payload["tipo"] == "panoramica" for sp in spans)


def test_cortes_de_cena_nas_trocas() -> None:
    frames, truth = build()
    cuts = [sp.start / 5 for sp in detect(_signals(frames, 40), ScreenParams()) if sp.kind == "cena"]
    for item in truth[1:]:
        assert any(abs(c - item.start_s) <= 0.5 for c in cuts), f"sem corte em {item.start_s}: {cuts}"


@needs_ffmpeg
def test_etapas_leem_o_proxy_e_geram_eventos(tmp_path: Path, settings: Settings) -> None:
    frames, truth = build()
    proxy = tmp_path / "proxy.mp4"
    write_video(settings, proxy, frames)

    def ctx(name: str, inputs: dict[str, StageResult]) -> StageContext:
        out = tmp_path / name
        out.mkdir()
        return StageContext(media_path=proxy, out_dir=out, settings=settings, inputs=inputs)

    signals = VideoSignalsStage().run(ctx("sig", {"proxy": StageResult(data={"proxy": str(proxy)})}))
    assert signals.data["signals"]["video.motion"]["hop_frames"] == vframes.HOP_FRAMES
    lengths = {m["length"] for m in signals.data["signals"].values()}
    assert len(lengths) == 1 and abs(lengths.pop() - len(frames)) <= 1

    scenes = VideoScenesStage().run(ctx("scn", {"video_signals": signals}))
    from cronista.audio.events import events_from_result

    events = events_from_result(scenes) or []
    kinds = {e.kind for e in events}
    assert {"loading", "menu", "idle", "cena"} <= kinds
    loading = next(e for e in events if e.kind == "loading")
    expected = next(t for t in truth if t.kind == "loading")
    assert abs(loading.evidence.start_frame / 60 - expected.start_s) <= 0.5
    assert loading.evidence.end_frame % vframes.HOP_FRAMES == 0  # grade de quadros inteiros a 60 fps


def test_proxy_ausente_e_erro_claro(tmp_path: Path, settings: Settings) -> None:
    from cronista.pipeline import StageError

    ctx = StageContext(
        media_path=tmp_path,
        out_dir=tmp_path,
        settings=settings,
        inputs={"proxy": StageResult(data={"proxy": str(tmp_path / "nao-existe.mp4")})},
    )
    with pytest.raises(StageError, match="proxy não encontrado"):
        VideoSignalsStage().run(ctx)

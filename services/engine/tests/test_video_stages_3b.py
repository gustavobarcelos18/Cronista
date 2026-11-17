"""Etapas da 3B rodando de ponta a ponta com entradas sintéticas: B-roll, tipos de menu, HUD oculto e idle."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from cronista.audio.events import EVENTS_KEY, events_from_result, write_events_file
from cronista.audio.signals import SIGNALS_KEY, write_signal
from cronista.config import Settings
from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource
from cronista.domain.models import StageResult
from cronista.pipeline import StageContext
from cronista.video.context_stages import BrollStage
from cronista.video.hud import HAS_HUD_KEY, IdleStage
from cronista.video.menus import MenuTypesStage
from tests.fakes_video import FakeEmbedder


def _ev(kind: str, a_s: int, b_s: int, **payload: object) -> AnalysisEvent:
    ev = Evidence(
        source=EvidenceSource.CENA,
        start_frame=a_s * 60,
        end_frame=b_s * 60,
        confidence=0.6,
        model="m",
        model_version="1",
        params_hash="h",
    )
    return AnalysisEvent(kind=kind, evidence=ev, payload=dict(payload))


def _events(tmp: Path, name: str, events: list[AnalysisEvent]) -> StageResult:
    out = tmp / name
    out.mkdir()
    return StageResult(data={EVENTS_KEY: write_events_file(out, events)})


def _embeddings(tmp: Path, arr: np.ndarray) -> StageResult:
    path = tmp / "emb.npy"
    np.save(path, arr.astype(np.float16))
    return StageResult(data={"embeddings": {"path": str(path), "fps": 1, "dim": arr.shape[1]}})


def _ctx(tmp: Path, settings: Settings, name: str, inputs: dict[str, StageResult]) -> StageContext:
    out = tmp / f"out-{name}"
    out.mkdir()
    return StageContext(media_path=tmp / "x.mp4", out_dir=out, settings=settings, inputs=inputs)


def _unit_rows(n: int, dim: int, seed: int) -> np.ndarray:
    rows = np.random.default_rng(seed).normal(size=(n, dim)).astype(np.float32)
    return rows / np.linalg.norm(rows, axis=1, keepdims=True)


def test_broll_etapa_gera_eventos_com_clima_tags_e_hud(tmp_path: Path, settings: Settings) -> None:
    fake = FakeEmbedder()
    scenes = _events(
        tmp_path,
        "scenes",
        [
            _ev("movimento_camera", 0, 10, tipo="parada"),
            _ev("movimento_camera", 20, 30, tipo="panoramica"),
            _ev("menu", 40, 50),
        ],
    )
    hud = _events(tmp_path, "hud", [_ev("hud_oculto", 0, 10)])
    hud.data[HAS_HUD_KEY] = True
    emb = _embeddings(tmp_path, _unit_rows(60, fake.dim, 1))
    done = BrollStage(fake).run(
        _ctx(tmp_path, settings, "b", {"video_scenes": scenes, "video_embeddings": emb, "video_hud": hud})
    )
    clips = events_from_result(done) or []
    assert [c.kind for c in clips] == ["broll", "broll"]
    assert [c.payload["hud"] for c in clips] == ["oculto", "visivel"]
    assert all({"clima", "utilidade", "tags", "cover_frame", "movimento"} <= set(c.payload) for c in clips)


def test_broll_sem_hud_na_sessao_fica_desconhecido(tmp_path: Path, settings: Settings) -> None:
    fake = FakeEmbedder()
    scenes = _events(tmp_path, "scenes", [_ev("movimento_camera", 0, 10, tipo="parada")])
    hud = _events(tmp_path, "hud", [])
    hud.data[HAS_HUD_KEY] = False
    emb = _embeddings(tmp_path, _unit_rows(20, fake.dim, 2))
    done = BrollStage(fake).run(
        _ctx(tmp_path, settings, "b", {"video_scenes": scenes, "video_embeddings": emb, "video_hud": hud})
    )
    assert [c.payload["hud"] for c in events_from_result(done) or []] == ["desconhecido"]


def test_tipos_de_menu_na_etapa_separam_grupos_e_poucos_menus_nao_colapsam(
    tmp_path: Path, settings: Settings
) -> None:
    dim = 8
    base = np.eye(dim, dtype=np.float32)
    rows = np.zeros((300, dim), np.float32)
    plan = [(0, 10, 0), (20, 30, 1), (40, 50, 0), (60, 70, 2), (80, 90, 1), (100, 110, 0)]
    rng = np.random.default_rng(4)
    for a, b, k in plan:
        rows[a:b] = base[k] + 0.3 + rng.normal(0, 0.02, (b - a, dim))  # fundo comum + marca do tipo
    scenes = _events(tmp_path, "scenes", [_ev("menu", a, b) for a, b, _ in plan])
    emb = _embeddings(tmp_path, rows)
    done = MenuTypesStage().run(
        _ctx(tmp_path, settings, "m", {"video_scenes": scenes, "video_embeddings": emb})
    )
    types = {e.payload["tipo_id"] for e in events_from_result(done) or []}
    assert len(types) == 3

    few = _events(tmp_path, "few", [_ev("menu", 0, 10), _ev("menu", 20, 30)])
    done = MenuTypesStage().run(
        _ctx(tmp_path, settings, "m2", {"video_scenes": few, "video_embeddings": emb})
    )
    assert len({e.payload["tipo_id"] for e in events_from_result(done) or []}) == 2  # 2 menus bem diferentes


def _signals(tmp: Path, still: float, luma: float, seconds: int) -> StageResult:
    out = tmp / "sig"
    out.mkdir(exist_ok=True)
    n = seconds * 5
    metas = {
        f"video.{name}": write_signal(
            out,
            f"video.{name}",
            np.full(n, value, np.float32),
            unit="0-1",
            source_track="video",
            version="1",
            params={},
            hop_frames=12,
        )
        for name, value in (("still", still), ("luma_mean", luma))
    }
    return StageResult(data={SIGNALS_KEY: {k: v.model_dump() for k, v in metas.items()}})


def _hud_result(tmp: Path, match: np.ndarray, has_hud: bool) -> StageResult:
    out = tmp / "hud"
    out.mkdir(exist_ok=True)
    meta = write_signal(
        out, "video.hud_match", match, unit="0-1", source_track="video", version="1", params={}, hop_frames=60
    )
    return StageResult(data={HAS_HUD_KEY: has_hud, SIGNALS_KEY: {"video.hud_match": meta.model_dump()}})


def test_idle_etapa_so_com_cena_parada_e_hud_inteiro(tmp_path: Path, settings: Settings) -> None:
    match = np.concatenate([np.full(30, 0.95), np.full(30, 0.5)]).astype(np.float32)
    done = IdleStage().run(
        _ctx(
            tmp_path,
            settings,
            "i",
            {
                "video_signals": _signals(tmp_path, 0.95, 0.3, 60),
                "video_hud": _hud_result(tmp_path, match, True),
            },
        )
    )
    idle = events_from_result(done) or []
    assert [(e.evidence.start_frame, e.evidence.end_frame) for e in idle] == [(0, 30 * 60)]


def test_idle_etapa_sem_hud_estavel_nao_detecta(tmp_path: Path, settings: Settings) -> None:
    done = IdleStage().run(
        _ctx(
            tmp_path,
            settings,
            "i",
            {
                "video_signals": _signals(tmp_path, 0.95, 0.3, 60),
                "video_hud": _hud_result(tmp_path, np.ones(60, np.float32), False),
            },
        )
    )
    assert (events_from_result(done) or []) == [] and done.warnings

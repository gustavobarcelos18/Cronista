"""HUD oculto (Fase 3B): gabarito estável da sessão e trechos sem ele, com quadros sintéticos em numpy."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from cronista.video.broll import Candidate, hud_state
from cronista.video.hud import HudParams, build_template, hidden_spans, match


def _session(n: int = 200, hidden: tuple[int, int] = (100, 130)) -> npt.NDArray[np.uint8]:
    """Mundo em ruído; HUD = barra clara e uma caixa nos cantos, fixas, ausentes em `hidden`."""
    rng = np.random.default_rng(5)
    frames = rng.integers(40, 120, size=(n, 90, 160), dtype=np.uint8)
    for i in range(n):
        if hidden[0] <= i < hidden[1]:
            continue
        frames[i, 80:88, 40:120] = 230  # barra de itens
        frames[i, 4:20, 130:156] = 200  # minimapa
    return frames


def test_gabarito_acha_o_hud_e_ignora_o_mundo() -> None:
    template = build_template(_session()[::4], HudParams())
    assert template.usable
    assert template.mask[80:88, 40:120].mean() > 0.8 and template.mask[30:60, 10:30].sum() == 0


def test_trecho_sem_hud_vira_hud_oculto() -> None:
    frames = _session()
    params = HudParams(min_seconds=10)
    score = match(frames, build_template(frames[::4], params), params)
    spans = hidden_spans(score, np.zeros(len(score), bool), params)
    assert len(spans) == 1
    start, end, conf = spans[0]
    assert abs(start - 100) <= 1 and abs(end - 130) <= 1 and 0.0 < conf <= 0.5


def test_menu_nao_conta_como_hud_oculto() -> None:
    frames = _session()
    params = HudParams(min_seconds=10)
    score = match(frames, build_template(frames[::4], params), params)
    blocked = np.zeros(len(score), bool)
    blocked[95:135] = True  # a tela estava em menu
    assert hidden_spans(score, blocked, params) == []


def test_sessao_sem_hud_estavel_nao_detecta_nada() -> None:
    rng = np.random.default_rng(1)
    frames = rng.integers(0, 255, size=(120, 90, 160), dtype=np.uint8)
    template = build_template(frames, HudParams())
    assert not template.usable
    assert match(frames, template, HudParams()).min() == 1.0


def test_estado_do_hud_na_tomada() -> None:
    from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource

    ev = AnalysisEvent(
        kind="hud_oculto",
        evidence=Evidence(
            source=EvidenceSource.CENA,
            start_frame=0,
            end_frame=600,
            confidence=0.4,
            model="m",
            model_version="1",
            params_hash="h",
        ),
    )
    dentro, fora = Candidate(60, 540, "parada", 0.6), Candidate(900, 1500, "parada", 0.6)
    assert hud_state(dentro, [ev], True) == "oculto"
    assert hud_state(fora, [ev], True) == "visivel"
    assert hud_state(dentro, [ev], False) == "desconhecido"


def test_tipos_de_menu_agrupam_parecidos_e_separam_diferentes() -> None:
    from cronista.video.menus import MenuParams, group

    rng = np.random.default_rng(2)
    base = np.eye(6, dtype=np.float32)[[0, 1, 2]]
    rows = [base[k] + rng.normal(0, 0.05, 6).astype(np.float32) for k in (0, 1, 0, 2, 1, 0)]
    vec = np.stack(rows)
    vec /= np.linalg.norm(vec, axis=1, keepdims=True)
    labels, cents = group(vec, MenuParams(similarity=0.8))
    assert len(cents) == 3 and labels[0] == labels[2] == labels[5] and labels[1] == labels[4]


def test_idle_so_com_cena_parada_e_hud_inteiro() -> None:
    from cronista.video.hud import IdleParams, idle_spans

    n = 60
    still = np.full(n, 0.95, np.float32)
    luma = np.full(n, 0.3, np.float32)
    match_ = np.ones(n, np.float32)
    match_[30:] = 0.4  # painel aberto sobre o jogo: HUD parcial
    spans = idle_spans(still, luma, match_, IdleParams(min_seconds=10))
    assert [(a, b) for a, b, _ in spans] == [(0, 30)]
    still[:10] = 0.2  # o personagem se mexeu: o trecho cai abaixo de 10 s
    assert idle_spans(still, luma, match_, IdleParams(min_seconds=10)) == [(10, 30, spans[0][2])]

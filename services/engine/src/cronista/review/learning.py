"""Aprendizado por manter/tirar trecho (Fase 7E): recalibra os pesos da relevância, simples e explicável.

Cada decisão do criador é um rótulo: `aceito`/`ajustado` = manter (1), `rejeitado` = tirar (0). Uma regressão
logística pequena (numpy) mede quanto cada sinal separa o que ele mantém do que ele tira, e o resultado é
**encolhido em direção aos pesos padrão** (quanto menos decisões, mais perto do padrão). A proposta traz uma
linha em português por peso. Nada é aplicado sem o criador aceitar (tabela só de inserção); o núcleo continua
universal: os pesos são do projeto, não do jogo.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, fields

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.db.models import MediaFile, RecordingSession, WeightCalibration
from cronista.relevance.engine import RelevanceParams
from cronista.relevance.service import load_segments
from cronista.review.decisions import current_decisions, decision_for

FEATURES = ("marcador", "emocao", "fala", "novidade", "pausa")
WEIGHT_NAMES = ("w_marker", "w_emotion", "w_speech", "w_novelty", "w_pause")
LABELS = {
    "w_marker": "marcador",
    "w_emotion": "emoção",
    "w_speech": "fala",
    "w_novelty": "novidade",
    "w_pause": "penalidade de menu/pausa",
}
MIN_DECISIONS = 20
MIN_PER_CLASS = 5
SHRINK_K = 30.0
"""Com `n` decisões, o peso final é `n/(n+K)` do aprendido e `K/(n+K)` do padrão."""
MIN_WEIGHT = 0.02


@dataclass
class Proposal:
    weights: dict[str, float]
    n_decisions: int
    kept: int
    removed: int
    explanation: list[str] = field(default_factory=list)


def defaults() -> dict[str, float]:
    p = RelevanceParams()
    return {n: float(getattr(p, n)) for n in WEIGHT_NAMES}


def collect_labeled(db: Session, project_id: int) -> tuple[np.ndarray, np.ndarray]:
    """Matriz de sinais (uma linha por segmento decidido) e rótulos 1 = manter, 0 = tirar."""
    rows: list[list[float]] = []
    labels: list[float] = []
    media_ids = db.scalars(
        select(MediaFile.id)
        .join(RecordingSession, MediaFile.session_id == RecordingSession.id)
        .where(RecordingSession.project_id == project_id)
    ).all()
    for media_id in media_ids:
        decisions = current_decisions(db, media_id)
        if not decisions:
            continue
        for seg in load_segments(db, media_id):
            d = decision_for(decisions, seg)
            if d is None:
                continue
            rows.append([float(seg.features.get(f, 0.0)) for f in FEATURES])
            labels.append(0.0 if d.decision == "rejeitado" else 1.0)
    return np.array(rows, dtype=float).reshape(-1, len(FEATURES)), np.array(labels, dtype=float)


def fit_logistic(
    x: np.ndarray, y: np.ndarray, steps: int = 800, lr: float = 0.5, l2: float = 0.05
) -> np.ndarray:
    """Coeficientes (um por sinal; os sinais já ficam entre 0 e 1, então são comparáveis)."""
    w = np.zeros(x.shape[1])
    b = 0.0
    for _ in range(steps):
        z = np.clip(x @ w + b, -30, 30)
        p = 1.0 / (1.0 + np.exp(-z))
        w -= lr * (x.T @ (p - y) / len(y) + l2 * w)
        b -= lr * float((p - y).mean())
    return w


def propose(db: Session, project_id: int) -> Proposal | None:
    """Pesos propostos, ou `None` se ainda há poucas decisões (mínimo de 20, com 5 de cada lado)."""
    x, y = collect_labeled(db, project_id)
    kept, removed = int((y == 1).sum()), int((y == 0).sum())
    if len(y) < MIN_DECISIONS or kept < MIN_PER_CLASS or removed < MIN_PER_CLASS:
        return None
    coef = fit_logistic(x, y)
    base = defaults()
    pos = np.clip(coef[:4], MIN_WEIGHT, None)
    learned_pos = pos / pos.sum() * sum(base[n] for n in WEIGHT_NAMES[:4])
    learned_pause = float(np.clip(-coef[4] / max(float(pos.sum()), 1e-9), 0.0, 1.0))
    learned = dict(zip(WEIGHT_NAMES, [*map(float, learned_pos), learned_pause], strict=True))
    alpha = len(y) / (len(y) + SHRINK_K)
    weights = {n: round(alpha * learned[n] + (1 - alpha) * base[n], 3) for n in WEIGHT_NAMES}
    explanation = []
    for n in WEIGHT_NAMES:
        delta = weights[n] - base[n]
        verb = "sobe" if delta > 0.01 else "desce" if delta < -0.01 else "fica"
        explanation.append(f"{LABELS[n]}: {verb} ({base[n]:.2f} → {weights[n]:.2f})")
    explanation.append(
        f"Base: {kept} mantidos e {removed} tirados. Só entram trechos decididos; revisar também os do "
        "meio da nota evita que a sugestão só reforce a nota atual."
    )
    return Proposal(weights, len(y), kept, removed, explanation)


def accept(db: Session, project_id: int, proposal: Proposal) -> WeightCalibration:
    row = WeightCalibration(
        project_id=project_id,
        weights=json.dumps(proposal.weights, sort_keys=True),
        n_decisions=proposal.n_decisions,
        explanation=json.dumps(proposal.explanation, ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    return row


def params_for_project(
    db: Session, project_id: int, overrides: Mapping[str, float] | None = None
) -> RelevanceParams:
    """Parâmetros de relevância do projeto: os padrão, com os pesos da última calibração aceita e, por cima,
    os limiares do perfil de jogo (`overrides`, o grupo `relevance`: lookback, nota mínima...), se houver."""
    row = db.scalar(
        select(WeightCalibration)
        .where(WeightCalibration.project_id == project_id)
        .order_by(WeightCalibration.id.desc())
    )
    params = RelevanceParams()
    if row is not None:
        valid = {f.name for f in fields(params)}
        saved = {k: float(v) for k, v in json.loads(row.weights).items() if k in valid}
        params = RelevanceParams(**{**params.__dict__, **saved})
    return RelevanceParams(**{**params.__dict__, **overrides}) if overrides else params

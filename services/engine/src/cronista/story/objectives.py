# ruff: noqa: E501
"""Objetivos e estados (Fase 5A): descoberta por fala com citação verificada, estados só de inserção.

Regra central: **declaração não é conclusão**. "Preciso achar comida" cria uma hipótese (`proposto`), nunca uma
conquista; mudar de plano ou comentar hipoteticamente não confirma nada. Toda transição de estado exige
evidência própria, e citação que não está na transcrição nunca vira objetivo confirmado (vai para a fila de
revisão como `incerto`).
"""

from __future__ import annotations

import csv
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.db.models import Objective, ObjectiveState
from cronista.domain.evidence import AnalysisEvent
from cronista.domain.frames import FPS
from cronista.story.models import ObjKind, ObjState


class EvidenceError(ValueError):
    """Transição de estado sem evidência (ou com evidência que não confere)."""


def normalize(text: str) -> str:
    plain = "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")
    return " ".join(re.findall(r"[a-z0-9]+", plain))


def speech_events(events: Sequence[AnalysisEvent]) -> list[AnalysisEvent]:
    return [e for e in events if e.kind == "fala" and e.evidence.quote]


def verify_citation(
    quote: str, speech: Sequence[AnalysisEvent], start_frame: int, end_frame: int, slack_s: float = 5.0
) -> bool:
    """A citação precisa estar, literalmente (sem acento nem pontuação), na fala dentro da janela."""
    wanted = normalize(quote)
    if not wanted:
        return False
    slack = int(slack_s * FPS)
    for e in speech:
        if e.evidence.end_frame < start_frame - slack or e.evidence.start_frame > end_frame + slack:
            continue
        if wanted in normalize(e.evidence.quote or ""):
            return True
    return False


@dataclass(frozen=True)
class Candidate:
    """Objetivo ou mudança de estado proposta por um extrator, sempre com a citação que a sustenta."""

    title: str
    kind: ObjKind
    state: ObjState
    quote: str
    start_frame: int
    end_frame: int
    confidence: float
    model: str = "regras"


class ObjectiveExtractor(Protocol):
    """Porta: regras (padrão, sem modelo) ou LLM local de tarefa curta e fechada (JSON validado)."""

    def extract(self, speech: Sequence[AnalysisEvent]) -> list[Candidate]: ...


DECLARATION = re.compile(
    r"\b(meu objetivo (e|eh|sera)|o objetivo (e|eh|sera)|a meta (e|eh)|vou (tentar )?"
    r"(construir|matar|achar|encontrar|derrotar|chegar|fazer|conseguir|pegar)|preciso (de |achar |encontrar |"
    r"construir |matar )|temos que|tenho que)\s*(?P<what>[^.!?]{3,80})",
    re.IGNORECASE,
)
CONCLUSION = re.compile(
    r"\b(consegui|terminei|matei|derrotei|achei|completei|finalmente)\b[^.!?]{0,60}", re.IGNORECASE
)
FAILURE = re.compile(r"\b(morri|perdi tudo|falhei|nao consegui|fracassei)\b[^.!?]{0,60}", re.IGNORECASE)
HYPOTHETICAL = re.compile(r"\b(se eu|e se|talvez|quem sabe|imagina se|poderia)\b", re.IGNORECASE)
STOP = {"de", "do", "da", "o", "a", "os", "as", "um", "uma", "que", "pra", "para", "e", "no", "na", "em"}


def keywords(text: str) -> set[str]:
    return {w for w in normalize(text).split() if len(w) > 3 and w not in STOP}


class RuleExtractor:
    """Extrator por regras em pt-BR. Conclusão só vale se houver palavras do objetivo na mesma fala."""

    def __init__(self, known_titles: Sequence[str] = ()) -> None:
        self.known = [(t, keywords(t)) for t in known_titles]

    def extract(self, speech: Sequence[AnalysisEvent]) -> list[Candidate]:
        out: list[Candidate] = []
        for e in speech:
            text = e.evidence.quote or ""
            norm = normalize(text)
            if HYPOTHETICAL.search(norm):
                continue  # comentário hipotético não vira objetivo nem estado
            frames = (e.evidence.start_frame, e.evidence.end_frame)
            if match := DECLARATION.search(norm):
                title = match.group(0).strip()
                out.append(Candidate(title, ObjKind.SECUNDARIO, ObjState.PROPOSTO, text, *frames, 0.4))
            # "não consegui" contém "consegui": a falha sai do texto antes de procurar a conclusão.
            for pattern, state, scope in (
                (CONCLUSION, ObjState.CONCLUIDO, FAILURE.sub(" ", norm)),
                (FAILURE, ObjState.FALHOU, norm),
            ):
                if not pattern.search(scope):
                    continue
                words = keywords(text)
                for title, kws in self.known:
                    if kws and words & kws:
                        out.append(Candidate(title, ObjKind.SECUNDARIO, state, text, *frames, 0.5))
        return out


def add_objective(
    db: Session,
    project_id: int,
    title: str,
    kind: ObjKind = ObjKind.SECUNDARIO,
    parent_id: int | None = None,
    origin: str = "fala",
) -> Objective:
    """Cria o objetivo, ou devolve o existente de mesmo título (uma retomada mantém o mesmo id)."""
    existing = db.scalar(
        select(Objective).where(Objective.project_id == project_id, Objective.title == title)
    )
    if existing is not None:
        return existing
    obj = Objective(project_id=project_id, kind=kind.value, title=title, parent_id=parent_id, origin=origin)
    db.add(obj)
    db.commit()
    return obj


def current_state(db: Session, objective_id: int, session_id: int | None = None) -> ObjectiveState | None:
    """Última linha não substituída (do objetivo, na sessão se informada)."""
    query = select(ObjectiveState).where(ObjectiveState.objective_id == objective_id)
    if session_id is not None:
        query = query.where(ObjectiveState.session_id == session_id)
    rows = list(db.scalars(query.order_by(ObjectiveState.id)))
    replaced = {r.replaces_id for r in rows if r.replaces_id is not None}
    live = [r for r in rows if r.id not in replaced]
    return live[-1] if live else None


def set_state(
    db: Session,
    objective_id: int,
    session_id: int,
    state: ObjState,
    *,
    source: str,
    quote: str | None,
    start_frame: int = 0,
    end_frame: int = 0,
    confidence: float = 0.0,
    model: str = "",
    origin: str = "auto",
    media_file_id: int | None = None,
) -> ObjectiveState:
    """Nova linha de estado. Exige evidência: citação (transcrição), ou fonte humana/marcador/evento."""
    if source == "transcricao" and not (quote and quote.strip()):
        raise EvidenceError("estado vindo da fala precisa de citação literal")
    if origin == "auto" and source == "humano":
        raise EvidenceError("fonte humana exige origem humana")
    if source not in ("transcricao", "humano") and (end_frame < start_frame or end_frame == 0):
        raise EvidenceError(f"estado vindo de '{source}' precisa do intervalo de quadros da evidência")
    prior = current_state(db, objective_id, session_id)
    row = ObjectiveState(
        objective_id=objective_id,
        session_id=session_id,
        state=state.value,
        media_file_id=media_file_id,
        start_frame=start_frame,
        end_frame=end_frame,
        ev_source=source,
        ev_quote=quote,
        ev_confidence=confidence,
        ev_model=model,
        origin=origin,
        replaces_id=prior.id if prior is not None else None,
    )
    db.add(row)
    db.commit()
    return row


@dataclass
class DiscoveryReport:
    confirmed: int = 0
    hypotheses: int = 0
    rejected: int = 0


def discover(
    db: Session,
    project_id: int,
    session_id: int,
    media_file_id: int,
    speech: Sequence[AnalysisEvent],
    extractor: ObjectiveExtractor,
    corroboration: Sequence[tuple[int, int]] = (),
    failure_corroboration: Sequence[tuple[int, int]] = (),
) -> DiscoveryReport:
    """Roda o extrator e grava. Citação que não confere é descartada; declaração fica `proposto` (hipótese).

    Conclusão (`concluido`) só se confirma com um marcador de conquista por perto (`corroboration`, em quadros);
    sem ele vira `incerto` e entra na fila de revisão.
    """
    report = DiscoveryReport()
    for cand in extractor.extract(speech):
        if not verify_citation(cand.quote, speech, cand.start_frame, cand.end_frame):
            report.rejected += 1
            continue
        obj = add_objective(db, project_id, cand.title, cand.kind)
        state = cand.state
        marks = {ObjState.CONCLUIDO: corroboration, ObjState.FALHOU: failure_corroboration}.get(state)
        if marks is not None and not any(
            a - 30 * FPS <= cand.end_frame and cand.start_frame <= b + 30 * FPS for a, b in marks
        ):
            state = (
                ObjState.INCERTO
            )  # declaração não é conclusão nem falha: sem marcador por perto, só hipótese
        prior = current_state(db, obj.id, session_id)
        if prior is not None and prior.origin == "humano":
            continue  # decisão do criador nunca é sobrescrita por reexecução
        already = db.scalar(
            select(ObjectiveState.id).where(
                ObjectiveState.objective_id == obj.id,
                ObjectiveState.session_id == session_id,
                ObjectiveState.state == state.value,
                ObjectiveState.ev_quote == cand.quote,
            )
        )
        if already is not None:
            continue  # (objetivo, estado, citação) já gravado: reexecutar não duplica nem alterna o estado
        set_state(
            db, obj.id, session_id, state, source="transcricao", quote=cand.quote,
            start_frame=cand.start_frame, end_frame=cand.end_frame, confidence=cand.confidence,
            model=cand.model, media_file_id=media_file_id,
        )  # fmt: skip
        if state in (ObjState.PROPOSTO, ObjState.INCERTO):
            report.hypotheses += 1
        else:
            report.confirmed += 1
    return report


def sync_profile_objectives(
    db: Session, project_id: int, objectives: Sequence[str], rules: Sequence[str]
) -> int:
    """Objetivos e regras do perfil/projeto (`objetivos`/`regras` do YAML) viram linhas, sem duplicar."""
    before = len(list(db.scalars(select(Objective).where(Objective.project_id == project_id))))
    for title in objectives:
        add_objective(db, project_id, title, ObjKind.PRINCIPAL, origin="perfil")
    for title in rules:
        add_objective(db, project_id, title, ObjKind.RESTRICAO, origin="perfil")
    after = len(list(db.scalars(select(Objective).where(Objective.project_id == project_id))))
    return after - before


def review_queue(db: Session, project_id: int) -> list[tuple[Objective, ObjectiveState]]:
    """Itens não confirmados (`proposto` ou `incerto`), nunca descartados nem afirmados (questionário Q14)."""
    out: list[tuple[Objective, ObjectiveState]] = []
    for obj in db.scalars(select(Objective).where(Objective.project_id == project_id)):
        state = current_state(db, obj.id)
        if state is not None and state.state in (ObjState.PROPOSTO.value, ObjState.INCERTO.value):
            out.append((obj, state))
    return out


def export_review_csv(items: Sequence[tuple[Objective, ObjectiveState]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["objetivo", "tipo", "estado", "citacao", "inicio_quadro", "decisao"])
        for obj, st in items:
            w.writerow([obj.title, obj.kind, st.state, st.ev_quote or "", st.start_frame, ""])
    return path

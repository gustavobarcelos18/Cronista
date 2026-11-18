"""Painel de embalagem do Studio (Fase 9D): títulos, thumbnails e Shorts da sessão e a escolha vigente.

Só leitura e montagem de dados: as decisões continuam sendo inserções (`title_choice`, `thumbnail_choice`,
`short_decision`). O que falta para publicar sai calculado aqui, sem escrever nada em disco.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel
from sqlalchemy.orm import Session

from cronista.packaging.publish import (
    APPROVED,
    MIN_SHORTS,
    current_short_decisions,
    list_shorts,
)
from cronista.packaging.service import TITLES_NAME, Origin, current_title
from cronista.packaging.titles import load_titles
from cronista.thumbnails.service import MANIFEST_NAME, current_thumbnail, load_manifest


class TitleOptionOut(BaseModel):
    n: int
    """Número da sugestão (1, 2, …), o mesmo de `cronista titulo-escolher --sugestao`."""
    text: str
    reason: str | None = None


class TitleOut(BaseModel):
    suggestions: list[TitleOptionOut] = []
    thumbnail_texts: list[str] = []
    provider: str | None = None
    chosen: str | None = None
    origin: Literal["sugerido", "editado", "proprio"] | None = None


class ThumbnailOut(BaseModel):
    variation: int
    file_name: str
    text: str | None = None
    position: str | None = None
    chosen: bool = False


Decision = Literal["pendente", "aprovado", "rejeitado"]


class ShortOut(BaseModel):
    key: str
    duration_s: float
    score: float
    reason: str
    has_clip: bool
    decision: Decision = "pendente"


class PackagingOut(BaseModel):
    title: TitleOut
    thumbnails: list[ThumbnailOut] = []
    shorts: list[ShortOut] = []
    approved_shorts: int = 0
    min_shorts: int = MIN_SHORTS
    missing: list[str] = []
    """O que falta escolher ou aprovar (o vídeo do Resolve é pedido só na hora de montar a pasta)."""
    ready: bool = False


class PublishOut(BaseModel):
    directory: str
    files: list[str]
    missing: list[str]
    ready: bool


def packaging_panel(
    db: Session, session_id: int, packaging_folder: Path, shorts_folder: Path
) -> PackagingOut:
    """Monta o painel. O que ainda não foi gerado vira lista vazia, nunca erro."""
    title = TitleOut()
    titles_path = packaging_folder / TITLES_NAME
    if titles_path.is_file():
        try:
            saved = load_titles(titles_path)
        except ValueError:  # arquivo editado à mão e quebrado: o painel segue sem sugestões
            saved = None
        if saved is not None:
            title.suggestions = [
                TitleOptionOut(n=n, text=o.text, reason=o.reason) for n, o in enumerate(saved.titles, start=1)
            ]
            title.thumbnail_texts = list(saved.thumbnail_texts)
            title.provider = saved.provider
    chosen_title = current_title(db, session_id)
    if chosen_title is not None:
        title.chosen = chosen_title.text
        title.origin = cast(Origin, chosen_title.origin)

    chosen_thumb = current_thumbnail(db, session_id)
    thumbnails: list[ThumbnailOut] = []
    if (packaging_folder / MANIFEST_NAME).is_file():
        try:
            thumbnails = [
                ThumbnailOut(
                    variation=int(e["variacao"]),
                    file_name=str(e["arquivo"]),
                    text=e.get("texto"),
                    position=e.get("posicao"),
                    chosen=chosen_thumb is not None and chosen_thumb.file_name == e["arquivo"],
                )
                for e in load_manifest(packaging_folder)
                if (packaging_folder / "thumbnails" / str(e["arquivo"])).is_file()
            ]
        except (ValueError, KeyError, TypeError, AttributeError):  # manifesto quebrado: segue sem ele
            thumbnails = []

    decisions = current_short_decisions(db, session_id)
    shorts: list[ShortOut] = []
    if (shorts_folder / f"shorts-{session_id}.json").is_file():
        try:
            shorts = [
                ShortOut(
                    key=e.key,
                    duration_s=e.duration_s,
                    score=e.score,
                    reason=e.reason,
                    has_clip=e.clip is not None,
                    decision=cast(Decision, decisions.get(e.key, "pendente")),
                )
                for e in list_shorts(shorts_folder, session_id)
            ]
        except (ValueError, KeyError, TypeError, AttributeError):  # manifesto quebrado: segue sem ele
            shorts = []
    approved = sum(1 for s in shorts if s.decision == APPROVED and s.has_clip)

    missing: list[str] = []
    if chosen_title is None:
        missing.append("escolher o título")
    if not any(t.chosen for t in thumbnails):
        missing.append("escolher a thumbnail")
    if approved < MIN_SHORTS:
        missing.append(f"aprovar Shorts ({approved} de {MIN_SHORTS})")
    return PackagingOut(
        title=title,
        thumbnails=thumbnails,
        shorts=shorts,
        approved_shorts=approved,
        missing=missing,
        ready=not missing,
    )

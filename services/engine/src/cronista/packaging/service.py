"""Títulos no banco e em disco (Fase 9C): pacote de entrada, importação das sugestões e escolha do criador."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.db.models import RecordingSession, TitleChoice
from cronista.packaging.titles import (
    TitleReport,
    TitleSet,
    build_title_pack,
    check_creator_title,
    load_titles,
    validate_titles,
)
from cronista.paths import STORY_PACK

Origin = Literal["sugerido", "editado", "proprio"]
PACK_NAME = "titulo-pack.json"
TITLES_NAME = "titulos.json"


class TitleError(Exception):
    """Título não pôde ser preparado, salvo ou escolhido; a mensagem já diz o que fazer."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


def write_title_pack(story_folder: Path, folder: Path) -> Path:
    """Lê o `story-pack.json` da sessão e grava o `titulo-pack.json` compacto na pasta de embalagem."""
    story_pack = story_folder / STORY_PACK
    if not story_pack.is_file():
        raise TitleError("rode `cronista story` antes")
    pack = build_title_pack(json.loads(story_pack.read_text(encoding="utf-8")))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / PACK_NAME
    path.write_text(json.dumps(pack, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def save_titles(folder: Path, title_set: TitleSet) -> TitleReport:
    """Valida e grava `titulos.json`. A versão anterior vira `titulos.v<N>.json` (histórico só de inserção).

    Com erros de validação, ou sem nenhum título (o `NullTitleProvider`), nada é gravado.
    """
    report = validate_titles(title_set)
    if not report.ok:
        raise TitleError("títulos inválidos", report.errors)
    if not report.titles:
        raise TitleError(
            "nenhum título sugerido; o criador titula sozinho (`cronista titulos-escolher --texto`)"
        )
    folder.mkdir(parents=True, exist_ok=True)
    current = folder / TITLES_NAME
    tmp = folder / f"{TITLES_NAME}.tmp"
    tmp.write_text(
        title_set.model_copy(
            update={"titles": report.titles, "thumbnail_texts": report.thumbnail_texts}
        ).model_dump_json(indent=1),
        encoding="utf-8",
    )
    if current.is_file():
        n = 1
        while (folder / f"titulos.v{n}.json").exists():
            n += 1
        current.replace(folder / f"titulos.v{n}.json")
    tmp.replace(current)
    return report


def record_title_choice(
    db: Session,
    session_id: int,
    folder: Path,
    *,
    suggestion: int | None = None,
    text: str | None = None,
) -> TitleChoice:
    """Registra a escolha (só inserção). `suggestion` (1, 2, …) sozinho = sugerido; `text` sozinho = próprio;
    os dois = o criador editou a sugestão. O texto do criador sempre vale, sem checagem de clichê."""
    if db.get(RecordingSession, session_id) is None:
        raise TitleError(f"sessão {session_id} não existe (veja `cronista status`)")
    if suggestion is None and text is None:
        raise TitleError('informe --sugestao N, --texto "..." ou os dois')
    suggested: str | None = None
    provider: str | None = None
    if suggestion is not None:
        path = folder / TITLES_NAME
        if not path.is_file():
            raise TitleError("sem sugestões salvas; rode `cronista titulos-import` antes")
        try:
            saved = load_titles(path)
        except ValueError as exc:
            raise TitleError(f"{exc}; rode `cronista titulos-import` de novo") from exc
        if not 1 <= suggestion <= len(saved.titles):
            raise TitleError(f"sugestão {suggestion} não existe (há {len(saved.titles)})")
        suggested, provider = saved.titles[suggestion - 1].text, saved.provider
    try:
        final = check_creator_title(text if text is not None else suggested or "")
    except ValueError as exc:
        raise TitleError(str(exc)) from exc
    origin: Origin = (
        "proprio" if suggested is None else ("sugerido" if text is None or final == suggested else "editado")
    )
    row = TitleChoice(
        session_id=session_id, text=final, origin=origin, suggested=suggested, provider=provider
    )
    db.add(row)
    db.commit()
    return row


def current_title(db: Session, session_id: int) -> TitleChoice | None:
    """A escolha vigente: a última linha inserida para a sessão."""
    return db.scalars(
        select(TitleChoice).where(TitleChoice.session_id == session_id).order_by(TitleChoice.id.desc())
    ).first()


def title_history(db: Session, session_id: int) -> list[TitleChoice]:
    return list(
        db.scalars(select(TitleChoice).where(TitleChoice.session_id == session_id).order_by(TitleChoice.id))
    )

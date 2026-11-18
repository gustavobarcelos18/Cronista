"""Thumbnails no banco e em disco (Fase 9B): gera as variações da sessão e registra a escolha do criador."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.config import Settings
from cronista.db.models import RecordingSession, ThumbnailChoice
from cronista.finishing.brand import brand_dir
from cronista.finishing.loader import load_style
from cronista.montage import SessionPlanError, load_masters
from cronista.packaging.service import TITLES_NAME
from cronista.packaging.titles import check_creator_thumbnail_text, load_titles
from cronista.paths import STORY_PACK, thumbnails_in
from cronista.pipeline.gpu import GpuGate
from cronista.thumbnails.model import check_model_files, load_thumbnail_model
from cronista.thumbnails.render import ThumbnailError, ThumbnailItem, render_thumbnails

MANIFEST_NAME = "thumbnails.json"


@dataclass
class ThumbnailPackage:
    items: list[ThumbnailItem]
    manifest: Path
    warnings: list[str] = field(default_factory=list)


def _manifest_entry(item: ThumbnailItem) -> dict[str, Any]:
    v = item.variation
    return {
        "variacao": v.n,
        "arquivo": item.path.name,
        "arquivo_id": v.frame.file_id,
        "segmento_id": v.frame.segment_id,
        "instante_s": v.frame.t_s,
        "nota": v.frame.score,
        "beat": v.frame.beat,
        "texto": v.text,
        "posicao": v.position,
    }


def suggested_texts(folder: Path) -> list[str]:
    """Textos de thumbnail que o `/titular` sugeriu (`titulos.json`); sem o arquivo, nenhum."""
    path = folder / TITLES_NAME
    return list(load_titles(path).thumbnail_texts) if path.is_file() else []


def render_session_thumbnails(
    db: Session,
    session_id: int,
    settings: Settings,
    story_folder: Path,
    folder: Path,
    *,
    texts: list[str] | None = None,
    day: int | None = None,
    count: int = 3,
    serie: str = "",
    gate: GpuGate | None = None,
) -> ThumbnailPackage:
    """Gera 2 a 3 variações. Texto do criador (`texts`) ganha do sugerido; sem nenhum dos dois, só o frame."""
    session = db.get(RecordingSession, session_id)
    if session is None:
        raise ThumbnailError(f"sessão {session_id} não existe (veja `cronista status`)")
    story_pack = story_folder / STORY_PACK
    if not story_pack.is_file():
        raise ThumbnailError("rode `cronista story` antes")
    pack = json.loads(story_pack.read_text(encoding="utf-8"))
    resolved, _ = load_style(settings, serie)
    directory = brand_dir(settings.brand_dir)
    model = load_thumbnail_model(directory)
    problems = check_model_files(model, directory)
    if problems:
        raise ThumbnailError("; ".join(problems))
    try:
        masters, notes = load_masters(db, session)
    except SessionPlanError as exc:
        raise ThumbnailError(str(exc)) from exc
    if texts:
        chosen = [check_creator_thumbnail_text(t, model.text.max_words) for t in texts]
    else:
        chosen = [t for t in suggested_texts(folder) if len(t.split()) <= model.text.max_words]
    rendered = render_thumbnails(
        pack,
        masters,
        model,
        resolved.brand.visual,
        thumbnails_in(folder),
        settings,
        texts=chosen,
        day=day,
        count=count,
        brand_dir=directory,
        gate=gate,
    )
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / MANIFEST_NAME
    manifest.write_text(
        json.dumps([_manifest_entry(i) for i in rendered.items], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return ThumbnailPackage(rendered.items, manifest, [*notes, *rendered.warnings])


def load_manifest(folder: Path) -> list[dict[str, Any]]:
    path = folder / MANIFEST_NAME
    if not path.is_file():
        raise ThumbnailError("sem thumbnails geradas; rode `cronista thumbnails` antes")
    data: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return data


def record_thumbnail_choice(db: Session, session_id: int, folder: Path, variation: int) -> ThumbnailChoice:
    """Registra a variação escolhida (só inserção; a última linha vale)."""
    if db.get(RecordingSession, session_id) is None:
        raise ThumbnailError(f"sessão {session_id} não existe (veja `cronista status`)")
    entries = load_manifest(folder)
    entry = next((e for e in entries if e["variacao"] == variation), None)
    if entry is None:
        raise ThumbnailError(
            f"variação {variation} não existe (há {', '.join(str(e['variacao']) for e in entries)})"
        )
    if not (thumbnails_in(folder) / entry["arquivo"]).is_file():
        raise ThumbnailError(f"{entry['arquivo']} não existe mais; rode `cronista thumbnails` de novo")
    row = ThumbnailChoice(
        session_id=session_id,
        file_name=entry["arquivo"],
        variation=variation,
        text=entry.get("texto"),
        position=entry.get("posicao"),
    )
    db.add(row)
    db.commit()
    return row


def current_thumbnail(db: Session, session_id: int) -> ThumbnailChoice | None:
    """A escolha vigente: a última linha inserida para a sessão."""
    return db.scalars(
        select(ThumbnailChoice)
        .where(ThumbnailChoice.session_id == session_id)
        .order_by(ThumbnailChoice.id.desc())
    ).first()

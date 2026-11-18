# ruff: noqa: E501
"""Aprovação dos Shorts e pasta de publicação (Fase 9D).

O criador aprova ou rejeita cada Short renderizado (só inserção, vale a última linha). A pasta final reúne o que sobe para o
YouTube: o vídeo-alvo (renderizado por ele no Resolve), os Shorts aprovados, a thumbnail e o título escolhidos, mais um
`LEIA-ME.md` com o que foi gerado e o que ainda falta. Nada é publicado pelo app: é só organização, local, sem rede.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.db.models import RecordingSession, ShortDecision
from cronista.packaging.service import current_title
from cronista.thumbnails.service import current_thumbnail

APPROVED = "aprovado"
REJECTED = "rejeitado"
DEFAULT = "padrao"
DECISIONS = (APPROVED, REJECTED)
MIN_SHORTS = 3
"""Critério de aceite da Fase 9: pelo menos 3 Shorts aprovados."""
PUBLISH_DIR = "publicacao"


class PublishError(Exception):
    """A decisão ou a pasta de publicação não pôde ser feita; a mensagem já diz o que fazer."""


@dataclass(frozen=True)
class ShortEntry:
    key: str
    file_id: int
    start_frame: int
    duration_s: float
    score: float
    reason: str
    clip: Path | None
    """MP4 renderizado (o mais recente com esse trecho); `None` se ainda não foi renderizado."""


def _manifest(shorts_folder: Path, session_id: int) -> dict[str, Any]:
    path = shorts_folder / f"shorts-{session_id}.json"
    if not path.is_file():
        raise PublishError("sem Shorts; rode `cronista shorts-render` antes")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def list_shorts(shorts_folder: Path, session_id: int) -> list[ShortEntry]:
    """Candidatos do `shorts-<sessão>.json` com o MP4 pronto de cada um, na ordem do manifesto (por nota)."""
    out: list[ShortEntry] = []
    for row in _manifest(shorts_folder, session_id).get("candidatos", []):
        file_id, start = int(row["file_id"]), int(row["start_frame"])
        clips = sorted(
            shorts_folder.glob(f"short-{file_id}-{start}-{int(row['end_frame'])}-*.mp4"),
            key=lambda p: (p.stat().st_mtime, p.name),
        )
        out.append(
            ShortEntry(
                f"{file_id}-{start}",
                file_id,
                start,
                float(row["duracao_s"]),
                float(row["score"]),
                str(row["reason"]),
                clips[-1] if clips else None,
            )
        )
    return out


def record_short_decision(
    db: Session, session_id: int, shorts_folder: Path, short_key: str, decision: str
) -> ShortDecision:
    """Aprova, rejeita ou volta a pendente (`padrao`) um Short. Só inserção; a chave precisa existir no manifesto."""
    if db.get(RecordingSession, session_id) is None:
        raise PublishError(f"sessão {session_id} não existe (veja `cronista status`)")
    if decision not in (*DECISIONS, DEFAULT):
        raise PublishError(f"decisão inválida: {decision!r} (use {APPROVED}, {REJECTED} ou {DEFAULT})")
    entries = {e.key: e for e in list_shorts(shorts_folder, session_id)}
    if short_key not in entries:
        raise PublishError(f"Short {short_key!r} não existe (há {', '.join(entries) or 'nenhum'})")
    if decision == APPROVED and entries[short_key].clip is None:
        raise PublishError(f"Short {short_key!r} ainda não foi renderizado; rode `cronista shorts-render`")
    row = ShortDecision(session_id=session_id, short_key=short_key, decision=decision)
    db.add(row)
    db.commit()
    return row


def current_short_decisions(db: Session, session_id: int) -> dict[str, str]:
    """Decisão vigente por Short (`aprovado` ou `rejeitado`); `padrao` volta a pendente e some do mapa."""
    rows = db.scalars(
        select(ShortDecision).where(ShortDecision.session_id == session_id).order_by(ShortDecision.id)
    )
    latest = {r.short_key: r.decision for r in rows}
    return {k: v for k, v in latest.items() if v in DECISIONS}


@dataclass
class PublishReport:
    directory: Path
    files: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    """O que ainda falta para publicar (aparece também no `LEIA-ME.md`)."""

    @property
    def ready(self) -> bool:
        return not self.missing


def _copy(source: Path, target: Path) -> None:
    tmp = target.with_name(f"part-{target.name}")
    shutil.copy2(source, tmp)
    tmp.replace(target)


def readme_text(
    *,
    video: str | None,
    title: str | None,
    title_origin: str | None,
    thumbnail: str | None,
    thumbnail_text: str | None,
    shorts: list[tuple[str, ShortEntry]],
    pending: int,
    rejected: int,
    missing: list[str],
) -> str:
    """`LEIA-ME.md` determinístico: o que está na pasta, de onde veio e o que falta."""
    lines = [
        "# Pacote de publicação",
        "",
        "Gerado pelo Cronista. Nada foi publicado: confira e suba você mesmo.",
        "",
    ]
    lines += ["## Conteúdo", ""]
    lines.append(f"- Vídeo da série: `{video}`" if video else "- Vídeo da série: **ainda não incluído**")
    if title:
        lines.append(f"- Título (`titulo.txt`): {title}" + (f" ({title_origin})" if title_origin else ""))
    else:
        lines.append("- Título: **ainda não escolhido**")
    if thumbnail:
        lines.append(
            f"- Thumbnail (`{thumbnail}`)" + (f', texto "{thumbnail_text}"' if thumbnail_text else "")
        )
    else:
        lines.append("- Thumbnail: **ainda não escolhida**")
    lines.append(
        f"- Shorts aprovados: {len(shorts)}" + (f" (mínimo para a fase: {MIN_SHORTS})" if shorts else "")
    )
    for name, entry in shorts:
        lines.append(f"  - `{name}`: {entry.duration_s:.1f} s, nota {entry.score:.2f}; {entry.reason}")
    if pending or rejected:
        lines.append(f"- Shorts fora do pacote: {pending} pendente(s), {rejected} rejeitado(s)")
    lines += ["", "## O que falta", ""]
    lines += [f"- {m}" for m in missing] if missing else ["- Nada: o pacote está completo."]
    lines += [
        "",
        "## Lembretes",
        "",
        "- Os Shorts são 1080x1920 a 60 fps com legenda gravada; confira no celular se nada fica sob a interface da plataforma.",
        "- A thumbnail tem até 2 MB (limite do YouTube). O número do dia, se houver selo, foi o que você informou ao gerá-la.",
        "",
    ]
    return "\n".join(lines)


def build_publish_package(
    db: Session,
    session_id: int,
    shorts_folder: Path,
    packaging_folder: Path,
    *,
    video: Path | None = None,
    out: Path | None = None,
) -> PublishReport:
    """Reúne vídeo, Shorts aprovados, thumbnail e título escolhidos numa pasta, com o `LEIA-ME.md`.

    Refazer é seguro: os arquivos do pacote anterior (`short-*.mp4`, `thumbnail.jpg`, `titulo.txt`) são trocados pelos
    de agora; o vídeo só é copiado se vier em `video`. O que faltar vira aviso (e item do LEIA-ME), nunca um erro.
    """
    if db.get(RecordingSession, session_id) is None:
        raise PublishError(f"sessão {session_id} não existe (veja `cronista status`)")
    if video is not None and not video.is_file():
        raise PublishError(f"vídeo {video} não existe")
    target = out or packaging_folder / PUBLISH_DIR
    target.mkdir(parents=True, exist_ok=True)
    report = PublishReport(target)
    for old in [*target.glob("short-*.mp4"), target / "thumbnail.jpg", target / "titulo.txt"]:
        old.unlink(missing_ok=True)

    video_name: str | None = None
    if video is not None:
        video_name = video.name
        _copy(video, target / video_name)
        report.files.append(video_name)
    else:
        existing = [p for p in target.glob("*.mp4") if not p.name.startswith(("short-", "part-"))]
        if existing:
            video_name = sorted(existing)[0].name
            report.files.append(video_name)
        else:
            report.missing.append(
                "vídeo da série: renderize no Resolve e rode de novo com `--video <arquivo>`"
            )

    title = current_title(db, session_id)
    if title is not None:
        (target / "titulo.txt").write_text(title.text + "\n", encoding="utf-8")
        report.files.append("titulo.txt")
    else:
        report.missing.append("título: `cronista titulo-escolher`")

    thumb = current_thumbnail(db, session_id)
    thumb_name: str | None = None
    source = packaging_folder / "thumbnails" / thumb.file_name if thumb else None
    if source is not None and source.is_file():
        _copy(source, target / "thumbnail.jpg")
        thumb_name = "thumbnail.jpg"
        report.files.append(thumb_name)
    else:
        report.missing.append(
            "thumbnail: `cronista thumbnails` e `cronista thumbnail-escolher`"
            if thumb is None
            else f"thumbnail: {thumb.file_name} não existe mais; rode `cronista thumbnails` de novo"
        )

    decisions = current_short_decisions(db, session_id)
    entries = (
        list_shorts(shorts_folder, session_id)
        if (shorts_folder / f"shorts-{session_id}.json").is_file()
        else []
    )
    approved: list[tuple[str, ShortEntry]] = []
    for entry in entries:
        if decisions.get(entry.key) != APPROVED:
            continue
        if entry.clip is None:
            report.missing.append(f"Short {entry.key} aprovado, mas sem MP4; rode `cronista shorts-render`")
            continue
        name = f"short-{len(approved) + 1:02d}.mp4"
        _copy(entry.clip, target / name)
        approved.append((name, entry))
        report.files.append(name)
    if len(approved) < MIN_SHORTS:
        report.missing.append(f"Shorts: {len(approved)} aprovado(s), o plano pede pelo menos {MIN_SHORTS}")

    rejected = sum(1 for e in entries if decisions.get(e.key) == REJECTED)
    pending = sum(1 for e in entries if e.key not in decisions)
    (target / "LEIA-ME.md").write_text(
        readme_text(
            video=video_name,
            title=title.text if title else None,
            title_origin=title.origin if title else None,
            thumbnail=thumb_name,
            thumbnail_text=thumb.text if thumb else None,
            shorts=approved,
            pending=pending,
            rejected=rejected,
            missing=report.missing,
        ),
        encoding="utf-8",
    )
    report.files.append("LEIA-ME.md")
    return report

"""Tipos e auxiliares comuns aos comandos da CLI."""

from __future__ import annotations

import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.config import Settings, load_settings
from cronista.db.models import MediaFile
from cronista.story.service import MAX_TARGET_MIN


def _valid_target(value: float) -> float:
    if not 0 < value <= MAX_TARGET_MIN:
        raise typer.BadParameter(
            f"a duração-alvo deve ser maior que zero e de até {MAX_TARGET_MIN:g} minutos"
        )
    return value


TargetMinutes = Annotated[
    float, typer.Option(help="Duração-alvo do vídeo, em minutos", callback=_valid_target)
]


class AnalysisPart(StrEnum):
    AUDIO = "audio"
    VIDEO = "video"


class Reframe(StrEnum):
    DESFOQUE = "desfoque"
    RECORTE = "recorte"


class ShortChoice(StrEnum):
    APROVADO = "aprovado"
    REJEITADO = "rejeitado"
    PADRAO = "padrao"


def _pick_media(db: Session, session: int, file: str | None, *, existing_only: bool = False) -> MediaFile:
    """Sem filtro, usa o primeiro arquivo em ordem. Com filtro, exige uma correspondência única."""
    rows = db.scalars(
        select(MediaFile).where(MediaFile.session_id == session).order_by(MediaFile.ordinal, MediaFile.id)
    )
    media = [m for m in rows if not existing_only or Path(m.path).is_file()]
    if file is None and media:
        return media[0]
    if file is not None:
        exact = [m for m in media if file == m.path or file == Path(m.path).name]
        matches = exact or [m for m in media if file in Path(m.path).name]
        if len(matches) == 1:
            return matches[0]
        if matches:
            options = ", ".join(m.path for m in matches)
            raise typer.BadParameter(
                f"mais de um arquivo corresponde a {file!r}: {options}", param_hint="--file"
            )
        raise typer.BadParameter(
            f"nenhum arquivo corresponde a {file!r} na sessão {session}", param_hint="--file"
        )
    typer.echo(f"erro: sessão {session} sem arquivos disponíveis (veja `cronista status`)", err=True)
    raise typer.Exit(1)


def current_settings() -> Settings:
    """Configuração da máquina; os testes trocam esta função (`load_settings` deste módulo)."""
    settings = load_settings()
    settings.relevance_overrides = _profile_relevance_overrides(settings)
    return settings


def _profile_relevance_overrides(settings: Settings) -> dict[str, float] | None:
    """Limiares de relevância do perfil, para o núcleo usar o mesmo critério que a relevância usou (B9).

    Um perfil que não carrega não derruba os comandos que nem o usam; `relevance` e `story` o relatam.
    """
    from cronista.profiles import relevance_overrides

    try:
        return relevance_overrides(settings)
    except (FileNotFoundError, ValueError):
        return None


def profile_objectives(settings: Settings) -> tuple[list[str], list[str]]:
    """Objetivos e regras do perfil de jogo; sai com erro se o perfil configurado não carrega."""
    from cronista.profiles import load_settings_profile

    try:
        profile = load_settings_profile(settings)
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"erro: {exc}", err=True)
        raise typer.Exit(1) from exc
    return profile.objetivos, profile.regras


def force_utf8_output() -> None:
    """Força UTF-8 na saída: o console do Windows (cp1252) quebra com `→` e caminhos acentuados raros."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

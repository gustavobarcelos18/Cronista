"""Tipos e auxiliares comuns aos comandos da CLI."""

from __future__ import annotations

import sys
from enum import StrEnum
from pathlib import Path

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.config import Settings, load_settings
from cronista.db.models import MediaFile


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


def _pick_media(db: Session, session: int, file: str | None) -> MediaFile:
    """Primeiro arquivo da sessão (ou o primeiro cujo nome contém `file`); sai com erro se não houver."""
    media = [
        m
        for m in db.scalars(
            select(MediaFile).where(MediaFile.session_id == session).order_by(MediaFile.ordinal)
        )
        if file is None or file in Path(m.path).name
    ]
    if not media:
        typer.echo(f"erro: sessão {session} sem arquivos (veja `cronista status`)", err=True)
        raise typer.Exit(1)
    return media[0]


def current_settings() -> Settings:
    """Configuração da máquina; os testes trocam esta função (`load_settings` deste módulo)."""
    return load_settings()


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

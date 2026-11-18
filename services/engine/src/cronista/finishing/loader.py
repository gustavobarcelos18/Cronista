"""Carrega o estilo (brand kit + série) e a biblioteca pessoal a partir da configuração."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import ValidationError

from cronista.config import Settings
from cronista.finishing.brand import (
    ResolvedStyle,
    brand_dir,
    load_brand_kit,
    load_series_style,
    resolve_style,
)
from cronista.finishing.library import Library, load_library

StyleLoader = Callable[[], tuple[ResolvedStyle, Library | None] | None]
"""Devolve o estilo e a biblioteca, ou `None` quando o acabamento não está configurado."""


def load_style(settings: Settings, serie: str) -> tuple[ResolvedStyle, Library | None]:
    """Brand kit + série e a biblioteca pessoal (se `library_dir` estiver configurado)."""
    directory = brand_dir(settings.brand_dir)
    style = resolve_style(load_brand_kit(directory), load_series_style(directory, serie) if serie else None)
    library = load_library(settings.library_dir) if settings.library_dir else None
    return style, library


def default_loader(settings: Settings) -> StyleLoader:
    """Loader do Studio: usa `finishing_series`; brand kit ausente ou inválido = sem acabamento."""

    def load() -> tuple[ResolvedStyle, Library | None] | None:
        try:
            return load_style(settings, settings.finishing_series)
        except (FileNotFoundError, ValueError, ValidationError):
            return None

    return load

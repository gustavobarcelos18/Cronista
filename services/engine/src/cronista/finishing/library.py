"""Inventário da biblioteca pessoal (Fase 8A; plano 6.4): efeitos, transições, SFX e música do criador.

Os arquivos ficam fora do git (caminho em `config/*.local.yaml`, `library_dir`). Quem entra no app é o
**inventário**: `inventario.yaml` na pasta da biblioteca, com tags, origem e licença de cada item. Pacote de
terceiros só entra com licença registrada; música gerada por IA exige verificar o uso comercial antes de
monetizar.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from cronista.finishing.brand import ITEM_ID, BrandKit

INVENTORY_FILE = "inventario.yaml"
MEDIA_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".mov", ".mp4", ".webm", ".png"}

ItemKind = Literal["sfx", "meme", "transicao", "vinheta", "musica", "overlay"]


class LibraryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ITEM_ID)
    file: str = Field(min_length=1)
    """Caminho relativo à pasta da biblioteca."""
    kind: ItemKind
    tags: list[str] = []
    origin: str = Field(min_length=1)
    """De onde veio (ex.: "propria", "Biblioteca de Áudio do YouTube", nome do pacote)."""
    license: str = Field(min_length=1)
    """Licença registrada. `propria` para o que o criador produziu."""
    commercial_use: bool = True
    """Falso bloqueia o item no vídeo monetizado (ex.: gerador de IA de plano gratuito)."""
    bpm: float | None = Field(default=None, gt=0, le=300)
    mood: str | None = None

    @model_validator(mode="after")
    def _music_needs_bpm(self) -> LibraryItem:
        if self.kind == "musica" and self.bpm is None:
            raise ValueError(f"música {self.id!r} precisa de bpm (corte no beat)")
        return self


class Library(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[LibraryItem] = []

    @model_validator(mode="after")
    def _unique_ids(self) -> Library:
        ids = [i.id for i in self.items]
        repeated = sorted({i for i in ids if ids.count(i) > 1})
        if repeated:
            raise ValueError(f"ids repetidos no inventário: {repeated}")
        return self

    def get(self, item_id: str) -> LibraryItem | None:
        return next((i for i in self.items if i.id == item_id), None)

    def find(
        self,
        kind: ItemKind,
        *,
        tags: set[str] | None = None,
        mood: str | None = None,
        commercial: bool = True,
    ) -> list[LibraryItem]:
        """Itens do tipo, com todas as tags pedidas, ordenados por id (resultado determinístico)."""
        found = [
            i
            for i in self.items
            if i.kind == kind
            and (tags is None or tags <= set(i.tags))
            and (mood is None or i.mood == mood)
            and (i.commercial_use or not commercial)
        ]
        return sorted(found, key=lambda i: i.id)


def load_library(directory: Path) -> Library:
    path = directory / INVENTORY_FILE
    if not path.is_file():
        raise FileNotFoundError(f"inventário não encontrado: {path} (crie o {INVENTORY_FILE} na biblioteca)")
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: precisa ser um mapa YAML")
    return Library.model_validate(data)


def check_library(library: Library, directory: Path) -> list[str]:
    """Arquivo ausente, fora da pasta ou de formato desconhecido; arquivo na pasta sem inventário."""
    problems: list[str] = []
    root = directory.resolve()
    listed: set[Path] = set()
    for item in library.items:
        target = (directory / item.file).resolve()
        listed.add(target)
        if not target.is_relative_to(root):
            problems.append(f"{item.id}: {item.file!r} sai da pasta da biblioteca")
        elif not target.is_file():
            problems.append(f"{item.id}: arquivo {item.file!r} não existe")
        elif target.suffix.lower() not in MEDIA_EXTENSIONS:
            problems.append(f"{item.id}: formato {target.suffix!r} não suportado")
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS and path not in listed:
            problems.append(f"{path.relative_to(root).as_posix()}: arquivo sem registro no inventário")
    return problems


def check_brand_references(brand: BrandKit, library: Library) -> list[str]:
    """Ids do brand kit que não existem na biblioteca, ou que não podem ir para vídeo monetizado."""
    problems: list[str] = []
    for item_id in sorted(set(brand.sonic.item_ids())):
        item = library.get(item_id)
        if item is None:
            problems.append(f"brand kit usa {item_id!r}, que não está no inventário")
        elif not item.commercial_use:
            problems.append(f"brand kit usa {item_id!r}, sem licença para uso comercial")
    return problems

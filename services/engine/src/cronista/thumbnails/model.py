# ruff: noqa: E501
"""Modelo de thumbnail do canal (Fase 9B): layout declarativo em YAML, dentro do brand kit.

O criador ainda não definiu o modelo do canal (plano 6.7, "Em aberto" 4). O app entrega o **mecanismo**: tamanho, posição e
tamanho do texto, moldura, selo de dia e correção de cor ficam em `packages/brand-kit/thumbnail.yaml`, e o layout muda sem
mexer no código. Cores são papéis da paleta do brand kit (`primary`, `accent`...) ou `#RRGGBB`; nada de cor fixa no código.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from cronista.finishing.brand import HEX_COLOR, Palette, brand_dir

PALETTE_ROLES = ("primary", "secondary", "accent", "background", "text")
Position = Literal[
    "topo_esquerda", "topo_centro", "topo_direita", "centro", "base_esquerda", "base_centro", "base_direita"
]
THUMBNAIL_FILE = "thumbnail.yaml"
_HEX = re.compile(HEX_COLOR)


def check_color(value: str) -> str:
    if value not in PALETTE_ROLES and not _HEX.fullmatch(value):
        raise ValueError(f"cor inválida: {value!r} (use {', '.join(PALETTE_ROLES)} ou #RRGGBB)")
    return value


def resolve_color(value: str, palette: Palette) -> str:
    """Papel da paleta → `#RRGGBB` do brand kit; hex passa direto."""
    return getattr(palette, value) if value in PALETTE_ROLES else value


def _default_positions() -> list[Position]:
    return ["base_esquerda", "topo_direita", "base_centro"]


class TextStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    font: Literal["title", "body"] = "title"
    size_pct: float = Field(default=0.2, gt=0.03, le=0.5)
    """Altura da fonte, em fração da altura da imagem."""
    color: str = "text"
    stroke_color: str = "background"
    stroke_pct: float = Field(default=0.012, ge=0, le=0.05)
    uppercase: bool = True
    max_words: int = Field(default=4, ge=1, le=6)
    max_line_chars: int = Field(default=14, ge=4, le=40)
    margin_pct: float = Field(default=0.05, ge=0, le=0.2)
    positions: list[Position] = Field(default_factory=_default_positions, min_length=1)
    """Uma posição por variação (a variação N usa `positions[N % len]`)."""

    @model_validator(mode="after")
    def _colors(self) -> TextStyle:
        check_color(self.color)
        check_color(self.stroke_color)
        return self


class DayBadge(BaseModel):
    """Selo "Dia N". O número nunca é fixo em arquivo: vem de `--dia` na hora de gerar (o dia é decidido na edição)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    template: str = Field(default="Dia {n}", pattern=r".*\{n\}.*")
    position: Position = "topo_esquerda"
    size_pct: float = Field(default=0.09, gt=0.02, le=0.3)
    color: str = "background"
    fill: str = "primary"

    @model_validator(mode="after")
    def _colors(self) -> DayBadge:
        check_color(self.color)
        check_color(self.fill)
        return self


class ColorGrade(BaseModel):
    """Correção de cor leve que destaca a imagem na lista de recomendados (FFmpeg `eq` e `vignette`)."""

    model_config = ConfigDict(extra="forbid")

    saturation: float = Field(default=1.15, ge=0, le=3)
    contrast: float = Field(default=1.08, ge=0.5, le=2)
    brightness: float = Field(default=0.0, ge=-0.5, le=0.5)
    vignette: bool = True


class ThumbnailModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    width: int = Field(default=1280, ge=640, le=3840)
    height: int = Field(default=720, ge=360, le=2160)
    text: TextStyle = TextStyle()
    frame: str | None = None
    """Moldura (PNG com alfa) relativa à pasta do brand kit. Vazio = sem moldura."""
    day_badge: DayBadge = DayBadge()
    color: ColorGrade = ColorGrade()

    @model_validator(mode="after")
    def _sixteen_by_nine(self) -> ThumbnailModel:
        if abs(self.width * 9 - self.height * 16) > 16:
            raise ValueError(f"thumbnail do YouTube é 16:9 (recebi {self.width}x{self.height})")
        return self


def default_model() -> ThumbnailModel:
    """Modelo padrão enquanto o criador não define o do canal (valores ilustrativos)."""
    return ThumbnailModel()


def load_thumbnail_model(directory: Path | None = None) -> ThumbnailModel:
    """`thumbnail.yaml` do brand kit; sem o arquivo, vale o modelo padrão. Arquivo inválido é recusado."""
    path = brand_dir(directory) / THUMBNAIL_FILE
    if not path.is_file():
        return default_model()
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: precisa ser um mapa YAML")
    return ThumbnailModel.model_validate(data)


def check_model_files(model: ThumbnailModel, directory: Path) -> list[str]:
    """Problemas de arquivos referenciados (a moldura) que não existem na pasta do brand kit."""
    if not model.frame:
        return []
    target = (directory / model.frame).resolve()
    if not target.is_relative_to(directory.resolve()):
        return [f"moldura {model.frame!r} sai da pasta do brand kit"]
    if not target.is_file():
        return [f"moldura {model.frame!r} não existe em {directory}"]
    return []


def render_schema() -> str:
    return json.dumps(ThumbnailModel.model_json_schema(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> None:
    """Escreve `thumbnail.schema.json` em `packages/brand-kit/` (editores de YAML validam e completam com ele)."""
    target = brand_dir()
    target.mkdir(parents=True, exist_ok=True)
    (target / "thumbnail.schema.json").write_text(render_schema(), encoding="utf-8")
    print(f"Escrito {target / 'thumbnail.schema.json'}")


if __name__ == "__main__":
    main()

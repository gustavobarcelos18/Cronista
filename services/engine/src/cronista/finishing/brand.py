"""Brand kit (identidade visual e sonora) e estilo por série (Fase 8A; plano 6.4 e histórico §40).

Tudo é dado declarativo em YAML, versionado em `packages/brand-kit/`. O brand kit é a assinatura do canal;
o estilo da série (Q18) só **sobrepõe** o que muda naquela série e define o modo e o orçamento de cada efeito.
Nenhum arquivo de mídia mora aqui: o brand kit referencia itens da biblioteca pessoal por `id`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from cronista.config import find_repo_root
from cronista.finishing.effects import EffectKind, EffectMode

HEX_COLOR = r"^#[0-9A-Fa-f]{6}$"
ITEM_ID = r"^[a-z0-9][a-z0-9_-]*$"


class Palette(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: str = Field(pattern=HEX_COLOR)
    secondary: str = Field(pattern=HEX_COLOR)
    accent: str = Field(pattern=HEX_COLOR)
    background: str = Field(pattern=HEX_COLOR)
    text: str = Field(pattern=HEX_COLOR)


class PaletteOverride(BaseModel):
    """Cores que a série troca; o que não aparece fica como no brand kit."""

    model_config = ConfigDict(extra="forbid")

    primary: str | None = Field(default=None, pattern=HEX_COLOR)
    secondary: str | None = Field(default=None, pattern=HEX_COLOR)
    accent: str | None = Field(default=None, pattern=HEX_COLOR)
    background: str | None = Field(default=None, pattern=HEX_COLOR)
    text: str | None = Field(default=None, pattern=HEX_COLOR)


class Fonts(BaseModel):
    """Nomes de fonte (instalada no sistema) ou arquivo relativo à pasta do brand kit."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    files: list[str] = []
    """Arquivos de fonte versionados junto do brand kit (opcional; ex.: `fonts/Titulo.ttf`)."""


class DayCard(BaseModel):
    """Cartela "Dia N". O número nunca é fixo: vem do ajuste dos dias no Studio (plano 4 e 6.3)."""

    model_config = ConfigDict(extra="forbid")

    style: Literal["titulo_editavel", "remotion"] = "titulo_editavel"
    template: str = Field(default="Dia {n}", pattern=r".*\{n\}.*")
    duration_s: float = Field(default=3.0, gt=0, le=10)


class DeathCounter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: str = Field(default="Mortes: {n}", pattern=r".*\{n\}.*")
    position: Literal["topo_esquerda", "topo_direita", "base_esquerda", "base_direita"] = "topo_direita"


class Visual(BaseModel):
    model_config = ConfigDict(extra="forbid")

    palette: Palette
    fonts: Fonts
    lut: str | None = None
    """Arquivo `.cube` relativo à pasta do brand kit (cor da série). Vazio = sem LUT."""
    day_card: DayCard = DayCard()
    death_counter: DeathCounter = DeathCounter()
    frames: list[str] = []
    """Molduras (PNG com alfa) relativas à pasta do brand kit."""


class Sonic(BaseModel):
    """Identidade sonora: itens da biblioteca pessoal referenciados por `id` (plano 6.4)."""

    model_config = ConfigDict(extra="forbid")

    intro: str | None = Field(default=None, pattern=ITEM_ID)
    day_transition: str | None = Field(default=None, pattern=ITEM_ID)
    death_sound: str | None = Field(default=None, pattern=ITEM_ID)
    loudness_lufs: float = Field(default=-14.0, le=-8, ge=-30)
    """Alvo integrado da mixagem final (YouTube: -14 LUFS)."""
    mood_themes: dict[str, list[str]] = {}
    """Clima do capítulo → ids de trilhas da biblioteca (música por clima, plano 6.4)."""

    def item_ids(self) -> list[str]:
        singles = [i for i in (self.intro, self.day_transition, self.death_sound) if i]
        return singles + [i for ids in self.mood_themes.values() for i in ids]


class BrandKit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    name: str = Field(min_length=1)
    visual: Visual
    sonic: Sonic = Sonic()


class EffectPolicy(BaseModel):
    """Modo e orçamento de um efeito: a defesa contra "cara de template" (plano 6.4)."""

    model_config = ConfigDict(extra="forbid")

    mode: EffectMode = EffectMode.EDITAVEL
    max_per_minute: float = Field(default=1.0, ge=0, le=60)
    min_score: float = Field(default=0.5, ge=0, le=1)
    """Nota mínima do momento (0 a 1) para o efeito ser considerado; abaixo disso, nada é aplicado."""


DEFAULT_EFFECTS: dict[EffectKind, EffectPolicy] = {
    EffectKind.ZOOM: EffectPolicy(max_per_minute=2.0, min_score=0.55),
    EffectKind.SHAKE: EffectPolicy(mode=EffectMode.SUGERIR, max_per_minute=0.5, min_score=0.8),
    EffectKind.MUSICA: EffectPolicy(max_per_minute=1.0, min_score=0.0),
    EffectKind.SFX: EffectPolicy(max_per_minute=3.0, min_score=0.4),
    EffectKind.SFX_MEME: EffectPolicy(mode=EffectMode.SUGERIR, max_per_minute=0.5, min_score=0.6),
    EffectKind.PIADA_VISUAL: EffectPolicy(mode=EffectMode.SUGERIR, max_per_minute=0.3, min_score=0.6),
    EffectKind.CONTADOR_MORTES: EffectPolicy(mode=EffectMode.RENDERIZADO, max_per_minute=2.0, min_score=0.0),
    EffectKind.FREEZE_TEXTO: EffectPolicy(mode=EffectMode.SUGERIR, max_per_minute=0.4, min_score=0.7),
    EffectKind.BARRA_PROGRESSO: EffectPolicy(mode=EffectMode.RENDERIZADO, max_per_minute=1.0, min_score=0.0),
    EffectKind.LEGENDA_PONTUAL: EffectPolicy(mode=EffectMode.RENDERIZADO, max_per_minute=4.0, min_score=0.5),
    EffectKind.CARTELA_DIA: EffectPolicy(max_per_minute=2.0, min_score=0.0),
    # `sugerir` até conferir em prod se o `SetLUT` funciona no Resolve gratuito (o spike devolveu false; §60)
    EffectKind.COR_LUT: EffectPolicy(mode=EffectMode.SUGERIR, max_per_minute=60.0, min_score=0.0),
}
"""Padrão conservador: efeitos de humor e impacto só como sugestão; o criador liga o resto por série."""


class SeriesStyle(BaseModel):
    """Estilo por série (Q18): YAML sobre o brand kit, separado do perfil de jogo."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, pattern=ITEM_ID)
    title: str = ""
    palette: PaletteOverride = PaletteOverride()
    lut: str | None = None
    mood_themes: dict[str, list[str]] = {}
    effects: dict[EffectKind, EffectPolicy] = {}
    """Só os efeitos que mudam em relação a `DEFAULT_EFFECTS`."""
    max_effects_per_minute: float = Field(default=6.0, gt=0, le=60)
    """Teto somado de efeitos aplicados (editável ou renderizado) por minuto de vídeo."""

    @model_validator(mode="after")
    def _themes_not_empty(self) -> SeriesStyle:
        for mood, ids in self.mood_themes.items():
            if not ids:
                raise ValueError(f"clima {mood!r} sem nenhuma trilha")
        return self


class ResolvedStyle(BaseModel):
    """Brand kit + série já combinados: é o que as etapas do acabamento consomem."""

    model_config = ConfigDict(extra="forbid")

    brand: BrandKit
    series: str
    effects: dict[EffectKind, EffectPolicy]
    max_effects_per_minute: float

    def policy(self, kind: EffectKind) -> EffectPolicy:
        return self.effects[kind]


def resolve_style(brand: BrandKit, series: SeriesStyle | None = None) -> ResolvedStyle:
    """Aplica a série sobre o brand kit; sem série, vale o brand kit com os efeitos padrão."""
    effects = dict(DEFAULT_EFFECTS)
    if series is None:
        return ResolvedStyle(brand=brand, series="", effects=effects, max_effects_per_minute=6.0)
    effects.update(series.effects)
    overrides = {k: v for k, v in series.palette.model_dump().items() if v is not None}
    palette = brand.visual.palette.model_copy(update=overrides)
    visual = brand.visual.model_copy(update={"palette": palette, "lut": series.lut or brand.visual.lut})
    sonic = brand.sonic.model_copy(update={"mood_themes": {**brand.sonic.mood_themes, **series.mood_themes}})
    return ResolvedStyle(
        brand=brand.model_copy(update={"visual": visual, "sonic": sonic}),
        series=series.name,
        effects=effects,
        max_effects_per_minute=series.max_effects_per_minute,
    )


def brand_dir(configured: Path | None = None) -> Path:
    return configured or find_repo_root() / "packages" / "brand-kit"


def _read_mapping(path: Path) -> dict[str, Any]:
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: precisa ser um mapa YAML")
    return data


def load_brand_kit(directory: Path) -> BrandKit:
    path = directory / "brand.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"brand kit não encontrado: {path}")
    return BrandKit.model_validate(_read_mapping(path))


def load_series_style(directory: Path, name: str) -> SeriesStyle:
    if not name.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"nome de série inválido: {name!r}")
    path = directory / "series" / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"estilo da série {name!r} não encontrado em {path}")
    return SeriesStyle.model_validate(_read_mapping(path))


def check_brand_files(brand: BrandKit, directory: Path, series: SeriesStyle | None = None) -> list[str]:
    """Problemas de arquivos referenciados (LUT, molduras, fontes) que não existem na pasta do brand kit."""
    problems: list[str] = []
    wanted = [("fonte", f) for f in brand.visual.fonts.files]
    wanted += [("moldura", f) for f in brand.visual.frames]
    if brand.visual.lut:
        wanted.append(("LUT", brand.visual.lut))
    if series and series.lut:
        wanted.append(("LUT da série", series.lut))
    for kind, rel in wanted:
        target = (directory / rel).resolve()
        if not target.is_relative_to(directory.resolve()):
            problems.append(f"{kind} {rel!r} sai da pasta do brand kit")
        elif not target.is_file():
            problems.append(f"{kind} {rel!r} não existe em {directory}")
    return problems


def render_schemas() -> dict[str, str]:
    def dump(model: type[BaseModel]) -> str:
        return json.dumps(model.model_json_schema(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"

    return {"brand.schema.json": dump(BrandKit), "series.schema.json": dump(SeriesStyle)}


def main() -> None:
    """Escreve os JSON Schemas em `packages/brand-kit/` (editores de YAML validam e completam com eles)."""
    target = brand_dir()
    target.mkdir(parents=True, exist_ok=True)
    for filename, text in render_schemas().items():
        (target / filename).write_text(text, encoding="utf-8")
        print(f"Escrito {target / filename}")


if __name__ == "__main__":
    main()

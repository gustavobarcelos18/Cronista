"""Perfis declarativos de jogo (Fase 3C-2): só dados, nunca código.

O núcleo roda com o perfil genérico embutido. Um perfil de jogo (`profiles/<nome>.yaml`) só **acrescenta**:
regiões de HUD para OCR, ajustes de limiares sobre o genérico, rótulos de contexto, ferramentas de câmera
para sugerir B-roll e objetivos/regras. Nenhum módulo do núcleo importa um perfil nem cita um jogo
(`tests/test_profiles.py` falha se isso acontecer).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cronista.config import Settings, find_repo_root
from cronista.relevance.engine import RelevanceParams
from cronista.video.hud import HudParams, IdleParams
from cronista.video.models import build_video_models
from cronista.video.ports import HudRegionSpec, VideoModels
from cronista.video.screen_state import ScreenParams

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

THRESHOLD_GROUPS: dict[str, type] = {
    "screen": ScreenParams,
    "hud": HudParams,
    "idle": IdleParams,
    "relevance": RelevanceParams,
}
"""Grupos de limiares ajustáveis por perfil -> dataclass de parâmetros do núcleo."""


class HudRegion(BaseModel):
    """Retângulo do HUD em coordenadas relativas (0 a 1), lido só quando o perfil pede."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)
    read: Literal["text", "number", "icon"] = "text"
    tag_theme: bool = False
    """O texto lido vira tag de tema do B-roll (ex.: bioma do minimapa)."""

    @model_validator(mode="after")
    def _inside_frame(self) -> HudRegion:
        if self.x + self.w > 1.0001 or self.y + self.h > 1.0001:
            raise ValueError(f"região {self.name!r} passa da borda do quadro")
        return self


class CameraTool(BaseModel):
    """Ferramenta de câmera do jogo, usada para sugerir ao criador gravar uma tomada de B-roll."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    hint: str = ""


class GameProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    title: str = ""
    hud_regions: list[HudRegion] = []
    thresholds: dict[str, dict[str, float]] = {}
    context_labels: list[str] = []
    camera_tools: list[CameraTool] = []
    objetivos: list[str] = []
    regras: list[str] = []

    @field_validator("thresholds")
    @classmethod
    def _known_thresholds(cls, value: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
        for group, items in value.items():
            if group not in THRESHOLD_GROUPS:
                raise ValueError(
                    f"grupo de limiar desconhecido: {group!r} (válidos: {sorted(THRESHOLD_GROUPS)})"
                )
            valid = {f.name for f in dataclasses.fields(THRESHOLD_GROUPS[group])}
            unknown = sorted(set(items) - valid)
            if unknown:
                raise ValueError(f"limiar desconhecido em {group!r}: {unknown} (válidos: {sorted(valid)})")
        return value

    @model_validator(mode="after")
    def _unique_regions(self) -> GameProfile:
        names = [r.name for r in self.hud_regions]
        if len(names) != len(set(names)):
            raise ValueError("nomes de região de HUD repetidos")
        return self


GENERIC = GameProfile(name="generico", title="Perfil genérico (universal, sem ajuste por jogo)")
"""Perfil embutido: não acrescenta nada. O núcleo funciona só com ele."""


def apply_thresholds[ParamsT: DataclassInstance](
    profile: GameProfile, group: str, params: ParamsT
) -> ParamsT:
    """Devolve `params` com os ajustes do perfil para o grupo (cópia; o genérico fica intacto)."""
    changes = profile.thresholds.get(group, {})
    if not changes:
        return params
    return dataclasses.replace(params, **changes)


def load_profile(path: Path) -> GameProfile:
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: o perfil precisa ser um mapa YAML")
    return GameProfile.model_validate(data)


def resolve_profile(name: str, profiles_dir: Path) -> GameProfile:
    """`''` ou `generico` = embutido; qualquer outro nome lê `profiles_dir/<nome>.yaml`."""
    if name in ("", GENERIC.name):
        return GENERIC
    if not name.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"nome de perfil inválido: {name!r}")
    path = profiles_dir / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Perfil {name!r} não encontrado em {profiles_dir}")
    return load_profile(path)


def hud_region_specs(profile: GameProfile) -> tuple[HudRegionSpec, ...]:
    return tuple(HudRegionSpec(r.name, r.x, r.y, r.w, r.h, r.read, r.tag_theme) for r in profile.hud_regions)


def load_settings_profile(settings: Settings) -> GameProfile:
    directory = settings.profiles_dir or find_repo_root() / "profiles"
    return resolve_profile(settings.profile, directory)


def build_models_with_profile(settings: Settings) -> VideoModels:
    """Modelos de vídeo da máquina mais o OCR do HUD, se o perfil configurado tiver regiões de HUD."""
    models = build_video_models(settings)
    regions = hud_region_specs(load_settings_profile(settings))
    if not regions or importlib.util.find_spec("rapidocr") is None:
        return models
    from cronista.video.adapters.rapidocr import RapidOcrReader

    return dataclasses.replace(models, hud_reader=RapidOcrReader(), hud_regions=regions)


def render_profile_schema() -> str:
    return json.dumps(GameProfile.model_json_schema(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> None:
    """Escreve `profiles/profile.schema.json` (editores de YAML usam para validar e completar)."""
    target = find_repo_root() / "profiles" / "profile.schema.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(render_profile_schema(), encoding="utf-8")
    print(f"Escrito {target}")


if __name__ == "__main__":
    main()

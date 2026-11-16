"""Configuração por ambiente: `config/<env>.yaml` (versionado) + `config/<env>.local.yaml` (fora do git)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

DEFAULT_HOTKEYS: dict[str, str | None] = {
    "momento": "<f13>",
    "novo_dia": "<f14>",
    "morte_falha": "<f15>",
    "engracado": "<f16>",
    "conquista": "<f17>",
    "construcao": "<f18>",
    "foto_progresso": "<f19>",
    "cinematica": "<f20>",
}
"""Teclas padrão (sintaxe do pynput). `null` desliga a tecla; `momento` e `novo_dia` são obrigatórias."""


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    env: str
    data_dir: Path
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    expected_fps: str = "60/1"
    proxy_height: int = 360
    proxy_crf: int = 28
    video_extensions: list[str] = [".mp4", ".mkv"]
    preview_encoder: str = "libx264"  # `h264_nvenc` em prod (GPU)
    preview_crf: int = 20
    preview_pre_s: float = 20.0
    preview_post_s: float = 10.0
    obs_host: str = "localhost"
    obs_port: int = 4455
    obs_password: str | None = None  # só em *.local.yaml ou na variável CRONISTA_OBS_PASSWORD
    marker_hotkeys: dict[str, str | None] = DEFAULT_HOTKEYS
    watch_dir: Path | None = None  # pasta de gravação do OBS (caminho pessoal: só em *.local.yaml)
    watch_poll_seconds: float = 5.0
    settle_seconds: float = 10.0  # arquivo parado há tanto tempo = o OBS terminou de escrever
    abandoned_after_hours: float = 4.0  # diário aberto e arquivo parado há tanto = gravação interrompida
    gpu_gate: bool = False  # `dev` não tem GPU nem OBS; `prod` liga
    gpu_busy_percent: int | None = None  # opcional: GPU >= isso por outro programa = ocupada (nvidia-smi)
    gpu_poll_seconds: float = 5.0
    log_level: str = "INFO"

    @field_validator("marker_hotkeys")
    @classmethod
    def _merge_hotkeys(cls, value: dict[str, str | None]) -> dict[str, str | None]:
        """Trocar uma tecla no YAML não apaga as outras: o que não vem na config fica no padrão."""
        return {**DEFAULT_HOTKEYS, **value}

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cronista.db"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"


def find_repo_root(start: Path | None = None) -> Path:
    """Sobe a partir de `start` até achar a pasta que contém `config/dev.yaml`."""
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "config" / "dev.yaml").is_file():
            return candidate
    raise FileNotFoundError("Raiz do repositório não encontrada (procurei config/dev.yaml)")


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: esperado um mapeamento YAML")
    return data


def load_settings(env: str | None = None, config_dir: Path | None = None) -> Settings:
    """Carrega o ambiente (`CRONISTA_ENV`, padrão `dev`); o `.local.yaml` sobrepõe o versionado."""
    env = env or os.environ.get("CRONISTA_ENV", "dev")
    if config_dir is None:
        override = os.environ.get("CRONISTA_CONFIG_DIR")
        config_dir = Path(override) if override else find_repo_root() / "config"
    base = _read_yaml(config_dir / f"{env}.yaml")
    if not base:
        raise FileNotFoundError(f"Configuração {config_dir / f'{env}.yaml'} não encontrada")
    data = _deep_merge(base, _read_yaml(config_dir / f"{env}.local.yaml"))
    settings = Settings.model_validate(data)
    password = os.environ.get("CRONISTA_OBS_PASSWORD")
    if password:
        settings = settings.model_copy(update={"obs_password": password})
    if not settings.data_dir.is_absolute():
        # Caminhos relativos valem a partir da raiz do repositório (pai da pasta config).
        settings = settings.model_copy(update={"data_dir": (config_dir.parent / settings.data_dir).resolve()})
    return settings

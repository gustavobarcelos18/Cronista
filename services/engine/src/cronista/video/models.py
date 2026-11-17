"""Quais modelos de vídeo existem nesta máquina (Fase 3B).

Sem `video_embedder` na configuração (o padrão) ou sem o grupo `ml`, a análise de vídeo roda só a 3A, em CPU.
Sem `video_embedder` na configuração (o padrão) ou sem o grupo `ml`, o vídeo roda só a 3A, em CPU.
"""

from __future__ import annotations

from cronista.audio.models import missing_ml_packages
from cronista.config import Settings
from cronista.video.ports import FrameEmbedder, VideoModels


def build_video_models(settings: Settings) -> VideoModels:
    if not settings.video_embedder or missing_ml_packages():
        return VideoModels()
    from cronista.video.adapters.siglip import SiglipEmbedder

    return VideoModels(
        embedder=SiglipEmbedder(settings.models_path / "siglip", model_id=settings.video_embedder)
    )


CANDIDATES: dict[str, tuple[str, str]] = {
    "siglip-base": ("siglip", "google/siglip-base-patch16-224"),
    "siglip2-base": ("siglip2", "google/siglip2-base-patch16-224"),
    "siglip2-so400m": ("siglip2", "google/siglip2-so400m-patch14-384"),
    "clip-b32": ("clip", "openai/clip-vit-base-patch32"),
    "clip-l14": ("clip", "openai/clip-vit-large-patch14"),
    "siglip-so400m": ("siglip", "google/siglip-so400m-patch14-384"),
    "siglip2-large": ("siglip2", "google/siglip2-large-patch16-384"),
    "siglip2-giant": ("siglip2", "google/siglip2-giant-opt-patch16-384"),
}
"""Candidatos do `bench-video`: nome curto -> (família, checkpoint). Nomes de checkpoint: conferir."""


def make_candidate(settings: Settings, name: str) -> FrameEmbedder:
    from cronista.video.adapters.siglip import ClipEmbedder, Siglip2Embedder, SiglipEmbedder

    family, model_id = CANDIDATES[name]
    cls = {"siglip": SiglipEmbedder, "siglip2": Siglip2Embedder, "clip": ClipEmbedder}[family]
    return cls(settings.models_path / family, model_id=model_id)

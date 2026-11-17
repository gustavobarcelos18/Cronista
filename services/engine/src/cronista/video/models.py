"""Quais modelos de vídeo existem nesta máquina (Fase 3B).

Sem `video_embedder` na configuração (o padrão) ou sem o grupo `ml`, a análise de vídeo roda só a 3A, em CPU.
Sem `video_embedder` na configuração (o padrão) ou sem o grupo `ml`, o vídeo roda só a 3A, em CPU.
"""

from __future__ import annotations

from cronista.audio.models import missing_ml_packages
from cronista.config import Settings
from cronista.video.ports import VideoModels


def build_video_models(settings: Settings) -> VideoModels:
    if not settings.video_embedder or missing_ml_packages():
        return VideoModels()
    from cronista.video.adapters.siglip import SiglipEmbedder

    return VideoModels(
        embedder=SiglipEmbedder(settings.models_path / "siglip", model_id=settings.video_embedder)
    )

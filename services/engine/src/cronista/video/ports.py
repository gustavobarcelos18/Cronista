"""Porta do modelo de embeddings de imagem (Fase 3B).

O núcleo só conhece este contrato; SigLIP/CLIP reais entram como adaptador no PC com GPU (`prod`), e os testes
usam um fake determinístico. Embeddings saem **normalizados** (norma 1), então cosseno = produto escalar.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np
import numpy.typing as npt

from cronista.domain.types import Pause

if TYPE_CHECKING:
    from cronista.video.vlm import ScreenVLM

RgbFrames = npt.NDArray[np.uint8]
"""`(n, altura, largura, 3)`, RGB."""
RgbImage = npt.NDArray[np.uint8]
"""`(altura, largura, 3)`, RGB: um quadro só."""
Embeddings = npt.NDArray[np.float32]
"""`(n, dim)`, cada linha com norma 1."""


class FrameEmbedder(Protocol):
    name: str
    version: str
    options: dict[str, Any]
    """Hiperparâmetros que mudam o resultado (checkpoint, precisão): entram na chave de cache."""
    dim: int
    input_size: int
    """Lado do quadro quadrado que o modelo espera (ex.: 224); a etapa já entrega os quadros nesse tamanho."""

    def embed_images(self, frames: RgbFrames, *, pause: Pause) -> Embeddings:
        """Um embedding por quadro, em lotes internos; chama `pause` entre lotes (gate de GPU)."""
        ...

    def embed_text(self, texts: Sequence[str]) -> Embeddings:
        """Embeddings de texto no mesmo espaço das imagens (busca de B-roll por texto)."""
        ...


class HudReader(Protocol):
    """Lê o texto de recortes pequenos do HUD (OCR). Só roda nas regiões que o perfil declara (3C-3)."""

    name: str
    options: dict[str, Any]

    @property
    def version(self) -> str: ...

    def read(self, crops: Sequence[RgbFrames]) -> list[str]:
        """Um texto por recorte `(altura, largura, 3)` RGB (tamanhos podem diferir); vazio se nada legível."""
        ...


@dataclass(frozen=True)
class HudRegionSpec:
    """Região de HUD em coordenadas relativas ao quadro (0 a 1); vem do perfil, mas o núcleo só vê isto."""

    name: str
    x: float
    y: float
    w: float
    h: float
    read: str = "text"
    tag_theme: bool = False


@dataclass(frozen=True)
class VideoModels:
    """Modelos de vídeo disponíveis nesta máquina. Sem nenhum (`dev`), só rodam os sinais de CPU da 3A."""

    embedder: FrameEmbedder | None = None
    hud_reader: HudReader | None = None
    vlm: ScreenVLM | None = None
    hud_regions: tuple[HudRegionSpec, ...] = ()

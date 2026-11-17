"""Contrato de uma etapa do pipeline."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from cronista.config import Settings
from cronista.domain.models import StageResult


class StageError(Exception):
    """Falha esperada de uma etapa (arquivo inválido, por exemplo); a mensagem vai para o job."""


@dataclass(frozen=True)
class StageContext:
    media_path: Path
    out_dir: Path
    settings: Settings
    inputs: dict[str, StageResult]  # resultados das etapas listadas em `needs`
    wait_for_gpu: Callable[[], None] = lambda: None
    """Etapas longas chamam isto entre blocos: bloqueia com o OBS gravando ou jogo em tela cheia."""


_VARIANT_MAX = 100
_VARIANT_RE = re.compile(rf"[A-Za-z0-9._-]{{1,{_VARIANT_MAX}}}")


def make_variant(text: str) -> str:
    """Nome de variante seguro a partir de um texto livre (nome de modelo, por exemplo).

    Troca o que não é letra, número, `.`, `_` ou `-` por `-` e, se passar de 100 caracteres, corta e
    acrescenta um hash curto do texto original, para dois nomes longos parecidos não colidirem.
    É a única fonte da regra: `stage_variant` valida com a mesma expressão.
    """
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "x"
    if len(cleaned) > _VARIANT_MAX:
        digest = hashlib.sha256(text.encode()).hexdigest()[:8]
        cleaned = f"{cleaned[: _VARIANT_MAX - 9].rstrip('-')}-{digest}"
    return cleaned


def stage_variant(stage: Stage) -> str:
    """Variante da etapa (ex.: o modelo comparado no benchmark); vazia para a maioria.

    É um atributo opcional `variant: str` da etapa, lido aqui para as antigas não precisarem declará-lo.
    Vira nome de pasta no cache, então só aceita letras, números, `.`, `_` e `-`.
    """
    variant = str(getattr(stage, "variant", "") or "")
    if variant and not _VARIANT_RE.fullmatch(variant):
        raise ValueError(f"variante inválida '{variant}' na etapa '{stage.name}'")
    return variant


def stage_key(stage: Stage) -> str:
    """Nome com a variante (`nome:variante`): é o que `needs`, o relatório e os logs usam."""
    variant = stage_variant(stage)
    return f"{stage.name}:{variant}" if variant else stage.name


class Stage(Protocol):
    name: str
    version: str  # sobe quando a lógica muda: invalida o cache da etapa e das seguintes
    needs: tuple[str, ...]
    uses_gpu: bool

    def params(self, settings: Settings) -> dict[str, Any]:
        """Parâmetros que entram na chave de cache."""
        ...

    def run(self, ctx: StageContext) -> StageResult: ...

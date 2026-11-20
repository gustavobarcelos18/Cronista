"""Contratos da narrativa (Fases 5 e 5A): beats, capítulos, falas do roteiro e estados de objetivo.

Sem número de dia: o capítulo é a posição na série; o número do "Dia N" é decidido na edição (plano, seção 4).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from cronista.relevance.engine import SegmentClass


class Beat(StrEnum):
    SETUP = "setup"
    CONFLITO = "conflito"
    FALHA = "falha"
    VIRADA = "virada"
    CONQUISTA = "conquista"


class ObjState(StrEnum):
    PROPOSTO = "proposto"
    EM_ANDAMENTO = "em_andamento"
    CONCLUIDO = "concluido"
    FALHOU = "falhou"
    ABANDONADO = "abandonado"
    SUSPENSO = "suspenso"
    RETOMADO = "retomado"
    INCERTO = "incerto"


class ObjKind(StrEnum):
    PRINCIPAL = "principal"
    SECUNDARIO = "secundario"
    SUBOBJETIVO = "subobjetivo"
    RESTRICAO = "restricao"


class Span(BaseModel):
    """Trecho de um arquivo em segundos inteiros (a grade da Fase 4)."""

    file_id: int
    start_s: int
    end_s: int

    @property
    def segment_id(self) -> str:
        return f"{self.file_id}:{self.start_s}"


class ScriptLine(BaseModel):
    """Uma fala sugerida, ligada a um segmento (aceite da Fase 5) ou a uma janela reservada."""

    segment_id: str = Field(
        min_length=3,
        description="`segmento_id` do beat, ou `@gancho` / `@fecho` (janelas reservadas, histórico §67)",
    )
    text: str = Field(min_length=1)
    kind: Literal["narracao", "antecipacao", "convite"] = "narracao"
    """`convite`: pedido de like, convite à comunidade ou despedida; só vale em `@gancho` e `@fecho`
    e é decisão do criador (o validador pede confirmação)."""
    justification: str | None = None
    """Obrigatória na antecipação (plano 6.8): por que mostrar antes da hora."""
    est_s: float | None = None
    """Duração estimada falada; calculada na validação quando vem vazia."""
    start_s: float | None = None
    """Onde a fala entra, em segundos do arquivo; vazio = começo do primeiro espaço livre do segmento.

    Nas janelas reservadas (`@gancho`, `@fecho`) é o deslocamento, em segundos, dentro da janela."""


class Script(BaseModel):
    version: int = 1
    provider: str = "desconhecido"
    lines: list[ScriptLine] = Field(default_factory=list)


class PackWindow(BaseModel):
    """Intervalo em segundos do arquivo de origem."""

    inicio_s: float
    fim_s: float


class PackLiveSpeech(PackWindow):
    texto: str | None = Field(default=None, description="Ausente quando o pacote cortou a transcrição")


class PackBeat(BaseModel):
    segmento_id: str
    arquivo_id: int
    inicio_s: float
    fim_s: float
    beat: Beat
    classe: SegmentClass
    nota: float
    razoes: list[str]
    marcadores: list[str]
    fala_ao_vivo: list[PackLiveSpeech]
    lacunas: list[PackWindow]


class PackChapter(BaseModel):
    n: int
    alocado_s: float
    beats: list[PackBeat]


class PackObjective(BaseModel):
    id: int
    titulo: str
    tipo: ObjKind
    estado: ObjState | Literal["sem_estado"]
    citacao: str
    confirmado: bool


class PackProject(BaseModel):
    nome: str = ""
    jogo: str = ""


class PackReserva(BaseModel):
    """Janela de narração reservada fora das lacunas: gancho (abertura) e fecho (final), gravados à parte."""

    id: str
    onde: str
    max_s: float
    instrucao: str


class StoryPack(BaseModel):
    """`story-pack.json`: o recorte compacto que o roteirista recebe (Fase 5). Só fatos verificáveis."""

    projeto: PackProject
    alvo_s: float
    objetivos: list[PackObjective]
    instrucoes: list[str]
    capitulos: list[PackChapter]
    reservas: list[PackReserva] = Field(default_factory=list)
    truncado: bool = False

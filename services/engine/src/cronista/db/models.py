"""Tabelas da Fase 1. Sem `day_number`: o número do dia é da edição (plano mestre, seção 4)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    game: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    sessions: Mapped[list[RecordingSession]] = relationship(back_populates="project")


class RecordingSession(Base):
    """Uma gravação de duração variável (pode ter vários arquivos, por divisão automática do OBS)."""

    __tablename__ = "session"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"))
    folder: Mapped[str] = mapped_column(String(1000), unique=True)  # origem: pasta ou diário
    source_signature: Mapped[str | None] = mapped_column(String(100), default=None)
    """Tamanho do diário no momento da ingestão (o diário só cresce): se mudar, a sessão é reingerida."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped[Project] = relationship(back_populates="sessions")
    media_files: Mapped[list[MediaFile]] = relationship(
        back_populates="session", order_by="MediaFile.ordinal"
    )


class MediaFile(Base):
    __tablename__ = "media_file"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("session.id"))
    path: Mapped[str] = mapped_column(String(1000), unique=True)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)

    session: Mapped[RecordingSession] = relationship(back_populates="media_files")


class Job(Base):
    """Um job por (arquivo, etapa), atualizado no lugar. Estados: pending, running, done, failed."""

    __tablename__ = "job"
    __table_args__ = (UniqueConstraint("media_file_id", "stage", "variant"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    media_file_id: Mapped[int] = mapped_column(ForeignKey("media_file.id"))
    stage: Mapped[str] = mapped_column(String(100))
    variant: Mapped[str] = mapped_column(String(100), default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    cache_key: Mapped[str | None] = mapped_column(String(64), default=None)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Artifact(Base):
    """Saída de uma etapa, identificada pela chave de cache (hash de entrada + parâmetros + versão)."""

    __tablename__ = "artifact"
    __table_args__ = (UniqueConstraint("media_file_id", "stage", "variant"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    media_file_id: Mapped[int] = mapped_column(ForeignKey("media_file.id"))
    stage: Mapped[str] = mapped_column(String(100))
    variant: Mapped[str] = mapped_column(String(100), default="", server_default="")
    """Vazia na maioria das etapas; distingue duas execuções da mesma etapa (dois modelos, por exemplo)."""
    cache_key: Mapped[str] = mapped_column(String(64))
    result_path: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Event(Base):
    """Evento de análise (fala, risada, grito…) com a evidência embutida (plano da Fase 2, lacuna 2).

    Tempo em quadros inteiros a 60 fps dentro do arquivo. Pertence à execução que o produziu
    (`media_file_id + stage + variant`): reexecutar a etapa substitui as linhas dela, nunca duplica.
    """

    __tablename__ = "event"
    __table_args__ = (
        Index("ix_event_media_frame", "media_file_id", "start_frame"),
        Index("ix_event_producer", "media_file_id", "stage", "variant"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    media_file_id: Mapped[int] = mapped_column(ForeignKey("media_file.id"))
    stage: Mapped[str] = mapped_column(String(100))
    variant: Mapped[str] = mapped_column(String(100), default="", server_default="")
    kind: Mapped[str] = mapped_column(String(40))
    start_frame: Mapped[int] = mapped_column(Integer)
    end_frame: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20))  # EvidenceSource
    confidence: Mapped[float] = mapped_column(Float)
    model: Mapped[str] = mapped_column(String(100))
    model_version: Mapped[str] = mapped_column(String(100))
    params_hash: Mapped[str] = mapped_column(String(64))
    quote: Mapped[str | None] = mapped_column(Text, default=None)
    payload: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Marker(Base):
    """Marcador de hotkey (usado na 1B). Tempo em quadros inteiros a 60 fps dentro do arquivo."""

    __tablename__ = "marker"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("session.id"))
    media_file_id: Mapped[int | None] = mapped_column(ForeignKey("media_file.id"), default=None)
    marker_id: Mapped[str] = mapped_column(String(64))  # o `id` de `tipo|id`
    kind: Mapped[str] = mapped_column(String(40))
    media_frame: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20), default="journal")  # journal | file | synthetic
    phase: Mapped[str | None] = mapped_column(String(10), default=None)  # construção: start | end
    warning: Mapped[str | None] = mapped_column(Text, default=None)


class Objective(Base):
    """Objetivo do projeto (Fase 5A): principal, secundário, subobjetivo ou restrição/regra."""

    __tablename__ = "objective"
    __table_args__ = (Index("ix_objective_project", "project_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"))
    kind: Mapped[str] = mapped_column(String(20))  # principal | secundario | subobjetivo | restricao
    title: Mapped[str] = mapped_column(String(300))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("objective.id"), default=None)
    origin: Mapped[str] = mapped_column(String(20), default="perfil")  # perfil | fala | humano
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ObjectiveState(Base):
    """Estado de um objetivo numa sessão. Só inserção: o estado atual é a última linha não substituída.

    A evidência vai embutida (`ev_*`): a tabela `evidence` normalizada fica para quando o Studio precisar.
    """

    __tablename__ = "objective_state"
    __table_args__ = (Index("ix_objective_state_obj", "objective_id", "session_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    objective_id: Mapped[int] = mapped_column(ForeignKey("objective.id"))
    session_id: Mapped[int] = mapped_column(ForeignKey("session.id"))
    state: Mapped[str] = mapped_column(String(20))  # proposto, em_andamento, concluido, falhou, ...
    media_file_id: Mapped[int | None] = mapped_column(ForeignKey("media_file.id"), default=None)
    start_frame: Mapped[int] = mapped_column(Integer, default=0)
    end_frame: Mapped[int] = mapped_column(Integer, default=0)
    ev_source: Mapped[str] = mapped_column(String(20), default="transcricao")
    ev_quote: Mapped[str | None] = mapped_column(Text, default=None)
    ev_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    ev_model: Mapped[str] = mapped_column(String(100), default="")
    origin: Mapped[str] = mapped_column(String(10), default="auto")  # auto | humano
    replaces_id: Mapped[int | None] = mapped_column(ForeignKey("objective_state.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class NarrativeEvent(Base):
    """Acontecimento narrativo observado (conquista, dificuldade, decisão, falha), sempre com evidência."""

    __tablename__ = "narrative_event"
    __table_args__ = (Index("ix_narrative_event_session", "session_id", "start_frame"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("session.id"))
    media_file_id: Mapped[int | None] = mapped_column(ForeignKey("media_file.id"), default=None)
    kind: Mapped[str] = mapped_column(String(20))  # acontecimento | conquista | dificuldade | decisao | falha
    description: Mapped[str] = mapped_column(Text)
    start_frame: Mapped[int] = mapped_column(Integer)
    end_frame: Mapped[int] = mapped_column(Integer)
    ev_source: Mapped[str] = mapped_column(String(20), default="marcador")
    ev_quote: Mapped[str | None] = mapped_column(Text, default=None)
    ev_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    origin: Mapped[str] = mapped_column(String(10), default="auto")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class NarrativeLink(Base):
    """Relação entre objetivos/eventos (`contribui_para`, `depende_de`, `impede`, `retoma`, `resolve`)."""

    __tablename__ = "narrative_link"

    id: Mapped[int] = mapped_column(primary_key=True)
    src_kind: Mapped[str] = mapped_column(String(10))  # objective | event
    src_id: Mapped[int] = mapped_column(Integer)
    dst_kind: Mapped[str] = mapped_column(String(10))
    dst_id: Mapped[int] = mapped_column(Integer)
    relation: Mapped[str] = mapped_column(String(20))
    ev_quote: Mapped[str | None] = mapped_column(Text, default=None)
    hypothesis: Mapped[bool] = mapped_column(default=True)
    """Sem evidência a relação fica como hipótese (plano da 5A)."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SegmentDecision(Base):
    """Decisão do criador sobre um segmento (Fase 7C). Só inserção: vale a última linha não substituída.

    O segmento é identificado por `(media_file_id, seg_start_s)`, início da relevância. `ajustado`
    guarda os novos limites em `start_s`/`end_s` (segundos do arquivo).
    """

    __tablename__ = "segment_decision"
    __table_args__ = (Index("ix_segment_decision_seg", "media_file_id", "seg_start_s"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    media_file_id: Mapped[int] = mapped_column(ForeignKey("media_file.id"))
    seg_start_s: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(12))  # aceito | rejeitado | ajustado
    start_s: Mapped[float | None] = mapped_column(Float, default=None)
    end_s: Mapped[float | None] = mapped_column(Float, default=None)
    replaces_id: Mapped[int | None] = mapped_column(ForeignKey("segment_decision.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

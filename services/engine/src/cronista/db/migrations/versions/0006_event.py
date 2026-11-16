"""tabela event: eventos de análise com a evidência embutida

Lacuna técnica 2 (histórico §36, plano da Fase 2). A 5A normaliza estes campos na tabela `evidence`.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-16 23:10:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("media_file_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=100), nullable=False),
        sa.Column("variant", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("start_frame", sa.Integer(), nullable=False),
        sa.Column("end_frame", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=False),
        sa.Column("params_hash", sa.String(length=64), nullable=False),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["media_file_id"], ["media_file.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_event_media_frame", "event", ["media_file_id", "start_frame"])
    op.create_index("ix_event_producer", "event", ["media_file_id", "stage", "variant"])


def downgrade() -> None:
    op.drop_index("ix_event_producer", table_name="event")
    op.drop_index("ix_event_media_frame", table_name="event")
    op.drop_table("event")

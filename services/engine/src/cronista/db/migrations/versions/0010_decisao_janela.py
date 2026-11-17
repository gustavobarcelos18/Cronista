"""decisão presa à janela do segmento (Fase 7C): fim do segmento no momento da decisão

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-18 01:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("segment_decision") as batch:
        batch.add_column(sa.Column("seg_end_s", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("segment_decision") as batch:
        batch.drop_column("seg_end_s")

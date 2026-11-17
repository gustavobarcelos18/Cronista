"""decisões do criador sobre segmentos (Fase 7C), só inserção

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-17 23:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "segment_decision",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("media_file_id", sa.Integer(), nullable=False),
        sa.Column("seg_start_s", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=12), nullable=False),
        sa.Column("start_s", sa.Float(), nullable=True),
        sa.Column("end_s", sa.Float(), nullable=True),
        sa.Column("replaces_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["media_file_id"], ["media_file.id"]),
        sa.ForeignKeyConstraint(["replaces_id"], ["segment_decision.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_segment_decision_seg", "segment_decision", ["media_file_id", "seg_start_s"])


def downgrade() -> None:
    op.drop_index("ix_segment_decision_seg", table_name="segment_decision")
    op.drop_table("segment_decision")

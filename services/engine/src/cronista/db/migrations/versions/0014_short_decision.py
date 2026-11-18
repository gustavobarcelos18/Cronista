"""decisão do criador sobre cada Short (Fase 9D), só inserção

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-18 20:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "short_decision",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("short_key", sa.String(length=40), nullable=False),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_short_decision_session_key", "short_decision", ["session_id", "short_key"])


def downgrade() -> None:
    op.drop_index("ix_short_decision_session_key", table_name="short_decision")
    op.drop_table("short_decision")

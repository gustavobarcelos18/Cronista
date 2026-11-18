"""thumbnail escolhida pelo criador (Fase 9B), só inserção

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-18 18:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "thumbnail_choice",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=200), nullable=False),
        sa.Column("variation", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=80), nullable=True),
        sa.Column("position", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_thumbnail_choice_session", "thumbnail_choice", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_thumbnail_choice_session", table_name="thumbnail_choice")
    op.drop_table("thumbnail_choice")

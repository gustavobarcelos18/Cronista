"""título escolhido pelo criador (Fase 9C), só inserção

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-18 16:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "title_choice",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=200), nullable=False),
        sa.Column("origin", sa.String(length=10), nullable=False),
        sa.Column("suggested", sa.String(length=200), nullable=True),
        sa.Column("provider", sa.String(length=30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_title_choice_session", "title_choice", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_title_choice_session", table_name="title_choice")
    op.drop_table("title_choice")

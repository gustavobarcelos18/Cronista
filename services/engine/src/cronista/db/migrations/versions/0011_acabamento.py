"""acabamento no Studio (Fase 8E): ajustes de efeito por projeto e decisões por item, só inserção

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-18 14:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "finishing_setting",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("mode", sa.String(length=12), nullable=False),
        sa.Column("max_per_minute", sa.Float(), nullable=False),
        sa.Column("min_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_finishing_setting_project_kind", "finishing_setting", ["project_id", "kind"])
    op.create_table(
        "finishing_decision",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("item_key", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("decision", sa.String(length=12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_finishing_decision_session_item", "finishing_decision", ["session_id", "item_key"])


def downgrade() -> None:
    op.drop_index("ix_finishing_decision_session_item", table_name="finishing_decision")
    op.drop_table("finishing_decision")
    op.drop_index("ix_finishing_setting_project_kind", table_name="finishing_setting")
    op.drop_table("finishing_setting")

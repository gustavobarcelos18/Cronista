"""tabelas da memória narrativa (Fase 5A): objetivos, estados (só inserção), eventos e relações

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-17 22:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "objective",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["parent_id"], ["objective.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_objective_project", "objective", ["project_id"])
    op.create_table(
        "objective_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("objective_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("media_file_id", sa.Integer(), nullable=True),
        sa.Column("start_frame", sa.Integer(), nullable=False),
        sa.Column("end_frame", sa.Integer(), nullable=False),
        sa.Column("ev_source", sa.String(length=20), nullable=False),
        sa.Column("ev_quote", sa.Text(), nullable=True),
        sa.Column("ev_confidence", sa.Float(), nullable=False),
        sa.Column("ev_model", sa.String(length=100), nullable=False),
        sa.Column("origin", sa.String(length=10), nullable=False),
        sa.Column("replaces_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["objective_id"], ["objective.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"]),
        sa.ForeignKeyConstraint(["media_file_id"], ["media_file.id"]),
        sa.ForeignKeyConstraint(["replaces_id"], ["objective_state.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_objective_state_obj", "objective_state", ["objective_id", "session_id"])
    op.create_table(
        "narrative_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("media_file_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("start_frame", sa.Integer(), nullable=False),
        sa.Column("end_frame", sa.Integer(), nullable=False),
        sa.Column("ev_source", sa.String(length=20), nullable=False),
        sa.Column("ev_quote", sa.Text(), nullable=True),
        sa.Column("ev_confidence", sa.Float(), nullable=False),
        sa.Column("origin", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"]),
        sa.ForeignKeyConstraint(["media_file_id"], ["media_file.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_narrative_event_session", "narrative_event", ["session_id", "start_frame"])
    op.create_table(
        "narrative_link",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("src_kind", sa.String(length=10), nullable=False),
        sa.Column("src_id", sa.Integer(), nullable=False),
        sa.Column("dst_kind", sa.String(length=10), nullable=False),
        sa.Column("dst_id", sa.Integer(), nullable=False),
        sa.Column("relation", sa.String(length=20), nullable=False),
        sa.Column("ev_quote", sa.Text(), nullable=True),
        sa.Column("hypothesis", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("narrative_link")
    op.drop_index("ix_narrative_event_session", table_name="narrative_event")
    op.drop_table("narrative_event")
    op.drop_index("ix_objective_state_obj", table_name="objective_state")
    op.drop_table("objective_state")
    op.drop_index("ix_objective_project", table_name="objective")
    op.drop_table("objective")

"""sessão: assinatura da origem (tamanho do diário na ingestão)

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-16 18:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("session", sa.Column("source_signature", sa.String(length=100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("session") as batch:
        batch.drop_column("source_signature")

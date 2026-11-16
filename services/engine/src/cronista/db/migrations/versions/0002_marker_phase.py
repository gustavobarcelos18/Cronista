"""marcador: fase da construção (início/fim)

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-16 09:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("marker", sa.Column("phase", sa.String(length=10), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("marker") as batch:
        batch.drop_column("phase")

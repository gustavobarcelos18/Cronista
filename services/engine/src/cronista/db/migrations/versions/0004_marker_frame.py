"""marcador: tempo em quadros inteiros a 60 fps (substitui media_time_s em segundos)

Lacuna técnica 1 (histórico §36). Os valores existentes são convertidos arredondando ao quadro mais próximo.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-16 20:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

FPS = 60  # fixo na migração: não depende do código atual


def upgrade() -> None:
    op.add_column("marker", sa.Column("media_frame", sa.Integer(), nullable=True))
    op.execute(f"UPDATE marker SET media_frame = MAX(0, CAST(ROUND(media_time_s * {FPS}) AS INTEGER))")
    with op.batch_alter_table("marker") as batch:
        batch.alter_column("media_frame", existing_type=sa.Integer(), nullable=False)
        batch.drop_column("media_time_s")


def downgrade() -> None:
    op.add_column("marker", sa.Column("media_time_s", sa.Float(), nullable=True))
    op.execute(f"UPDATE marker SET media_time_s = media_frame * 1.0 / {FPS}")
    with op.batch_alter_table("marker") as batch:
        batch.alter_column("media_time_s", existing_type=sa.Float(), nullable=False)
        batch.drop_column("media_frame")

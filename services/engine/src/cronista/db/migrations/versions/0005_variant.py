"""artifact e job: coluna `variant` e unicidade por (arquivo, etapa, variante)

Lacuna técnica 3 (histórico §36, plano da Fase 2): duas execuções da mesma etapa (dois modelos no
benchmark) não podem se sobrescrever. As linhas existentes ficam com a variante vazia.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-16 23:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# O SQLite guarda a unicidade sem nome; a convenção dá a ela um nome previsível ao recriar a tabela.
_OLD = {"uq": "uq_%(table_name)s_%(column_0_N_name)s"}


def _swap(table: str, old: list[str], new: list[str]) -> None:
    with op.batch_alter_table(table, naming_convention=_OLD) as batch:
        batch.drop_constraint(f"uq_{table}_{'_'.join(old)}", type_="unique")
        batch.create_unique_constraint(f"uq_{table}_{'_'.join(new)}", new)


def upgrade() -> None:
    for table in ("artifact", "job"):
        op.add_column(table, sa.Column("variant", sa.String(length=100), nullable=False, server_default=""))
        _swap(table, ["media_file_id", "stage"], ["media_file_id", "stage", "variant"])


def downgrade() -> None:
    for table in ("artifact", "job"):
        # Variantes extras não cabem na unicidade antiga: ficam só as de variante vazia.
        op.execute(f"DELETE FROM {table} WHERE variant <> ''")
        _swap(table, ["media_file_id", "stage", "variant"], ["media_file_id", "stage"])
        with op.batch_alter_table(table) as batch:
            batch.drop_column("variant")

"""Engine SQLAlchemy e migrações programáticas."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_UPGRADE_LOCK = threading.Lock()
"""O Alembic tem um proxy global de operações: dois `upgrade` simultâneos (threads da API) se atropelam."""


def make_engine(db_path: Path) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


def upgrade_db(engine: Engine) -> None:
    """Aplica as migrações Alembic até a mais recente."""
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["connection_url"] = engine.url.render_as_string(hide_password=False)
    with _UPGRADE_LOCK:
        command.upgrade(cfg, "head")


@contextmanager
def open_db(db_path: Path, *, migrate: bool = True) -> Iterator[Session]:
    """`migrate=False` pula o Alembic (para quem já migrou o banco)."""
    engine = make_engine(db_path)
    if migrate:
        upgrade_db(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        with factory() as session:
            yield session
    finally:  # também quando o corpo levanta (ex.: `typer.Exit`): o arquivo do banco não fica preso
        engine.dispose()

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from cronista.db.models import Base
from cronista.db.session import MIGRATIONS_DIR, make_engine


def test_migration_creates_all_tables_and_no_day_number(db: Session) -> None:
    inspector = inspect(db.get_bind())
    tables = set(inspector.get_table_names())
    assert {t.name for t in Base.metadata.sorted_tables} <= tables
    for table in tables - {"alembic_version"}:
        assert "day_number" not in {c["name"] for c in inspector.get_columns(table)}


def test_migration_0004_converts_marker_seconds_to_frames_and_back(tmp_path: Path) -> None:
    engine = make_engine(tmp_path / "migracao.db")
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["connection_url"] = engine.url.render_as_string(hide_password=False)

    command.upgrade(cfg, "0003")
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO project (id, name, created_at) VALUES (1, 'p', '2026-11-16 00:00:00')")
        )
        conn.execute(
            text(
                "INSERT INTO session (id, project_id, folder, created_at) "
                "VALUES (1, 1, 'x', '2026-11-16 00:00:00')"
            )
        )
        for marker_id, seconds in (("a", 0.0), ("b", 12.5), ("c", 12.51), ("d", 403.233)):
            conn.execute(
                text(
                    "INSERT INTO marker (session_id, marker_id, kind, media_time_s, source) "
                    "VALUES (1, :id, 'momento', :s, 'file')"
                ),
                {"id": marker_id, "s": seconds},
            )

    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        columns = {c["name"] for c in inspect(conn).get_columns("marker")}
        assert "media_frame" in columns and "media_time_s" not in columns
        rows: dict[str, int] = dict(conn.execute(text("SELECT marker_id, media_frame FROM marker")).all())
    assert rows == {"a": 0, "b": 750, "c": 751, "d": 24194}

    command.downgrade(cfg, "0003")
    with engine.connect() as conn:
        back: dict[str, float] = dict(conn.execute(text("SELECT marker_id, media_time_s FROM marker")).all())
    assert back["b"] == 12.5 and back["d"] == pytest.approx(24194 / 60)
    engine.dispose()


def test_migration_0005_keeps_existing_rows_and_allows_variants(tmp_path: Path) -> None:
    engine = make_engine(tmp_path / "variante.db")
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["connection_url"] = engine.url.render_as_string(hide_password=False)

    command.upgrade(cfg, "0004")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO project (id, name, created_at) VALUES (1, 'p', '2026-11-16')"))
        conn.execute(
            text("INSERT INTO session (id, project_id, folder, created_at) VALUES (1, 1, 'x', '2026-11-16')")
        )
        conn.execute(
            text(
                "INSERT INTO media_file (id, session_id, path, ordinal, size_bytes) VALUES (1, 1, 'a', 0, 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO artifact (media_file_id, stage, cache_key, result_path, created_at) "
                "VALUES (1, 'audio', 'k', 'r', '2026-11-16')"
            )
        )
        conn.execute(
            text("INSERT INTO job (media_file_id, stage, status, attempts) VALUES (1, 'audio', 'done', 1)")
        )

    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT stage, variant FROM artifact")).all() == [("audio", "")]
        assert conn.execute(text("SELECT stage, variant, status FROM job")).all() == [("audio", "", "done")]
        assert "event" in inspect(conn).get_table_names()
    engine.dispose()


def test_d12_migrations_match_the_models_and_downgrade_to_base(tmp_path: Path) -> None:
    """`upgrade head` deixa o banco igual aos modelos"""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    engine = make_engine(tmp_path / "paridade.db")
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["connection_url"] = engine.url.render_as_string(hide_password=False)
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"modelos e migrações divergem: {str(diff)[:600]}"

    command.downgrade(cfg, "base")
    with engine.connect() as conn:
        assert set(inspect(conn).get_table_names()) <= {"alembic_version"}
    engine.dispose()

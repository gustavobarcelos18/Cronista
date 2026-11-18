"""Regressões da auditoria 10A (bloco D): cada teste falhava antes da correção."""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer.main

from cronista.cli import app
from cronista.packaging.publish import list_shorts
from cronista.shorts.candidates import ShortCandidate
from cronista.shorts.service import write_shorts
from tests.test_packaging_publish import candidate, make_shorts, session_id  # noqa: F401


def _params(command: str) -> set[str]:
    cmd = typer.main.get_command(app).commands[command]  # type: ignore[attr-defined]
    return {p.name for p in cmd.params if p.name}


def test_d1_packaging_commands_have_no_out_option() -> None:
    """`--out` gerava material que nenhum passo seguinte enxergava (as pastas lidas são fixas)."""
    for name in ("shorts", "shorts-render", "titulos", "thumbnails"):
        assert "out" not in _params(name), name


def test_d2_publish_reads_the_clip_recorded_in_the_manifest(session_id: int, tmp_path: Path) -> None:  # noqa: F811
    keys = make_shorts(tmp_path, session_id, 1)
    row = candidate(1, 600, 0.9)
    old = tmp_path / "short-1-600-1200-estilo-antigo.mp4"
    old.write_bytes(b"antigo")
    os.utime(old, (1, 1))  # o mtime mais antigo; o gravado no manifesto é o abc123 (mais novo)
    manifest = tmp_path / f"shorts-{session_id}.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["candidatos"][0]["clip"] = old.name  # o render atual usou o estilo antigo
    manifest.write_text(json.dumps(data), encoding="utf-8")
    (entry,) = list_shorts(tmp_path, session_id)
    assert entry.key == keys[0] and entry.clip == old and row["start_frame"] == 600


def test_d2_clip_that_failed_to_render_is_not_guessed_from_old_files(session_id: int, tmp_path: Path) -> None:  # noqa: F811
    make_shorts(tmp_path, session_id, 1)  # deixa um MP4 de um render anterior na pasta
    manifest = tmp_path / f"shorts-{session_id}.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["candidatos"][0]["clip"] = None  # o render desta vez falhou
    manifest.write_text(json.dumps(data), encoding="utf-8")
    (entry,) = list_shorts(tmp_path, session_id)
    assert entry.clip is None


def test_d2_write_shorts_records_the_rendered_clip(tmp_path: Path) -> None:
    c = ShortCandidate(1, 600, 1200, 900, 700, "marcador", 0.9, "pico", 10)
    path = write_shorts([c], tmp_path, 7, {"1-600": tmp_path / "short-1-600-1200-x.mp4"})
    row = json.loads(path.read_text(encoding="utf-8"))["candidatos"][0]
    assert row["clip"] == "short-1-600-1200-x.mp4"

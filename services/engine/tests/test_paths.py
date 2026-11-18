"""T3: a convenção de pastas de sessão num único lugar (`paths.py`)."""

from __future__ import annotations

import pathlib
import re
from pathlib import Path

from cronista.paths import SessionPaths, shorts_manifest_in, thumbnails_in


def test_session_paths_follow_the_data_layout(tmp_path: Path) -> None:
    p = SessionPaths(tmp_path, 7)
    assert p.story_dir == tmp_path / "story" / "7"
    assert p.script == tmp_path / "story" / "7" / "roteiro.json"
    assert p.packaging_dir == tmp_path / "packaging" / "7"
    assert p.publish_dir == tmp_path / "packaging" / "7" / "publicacao"
    assert p.shorts_manifest == tmp_path / "shorts" / "7" / "shorts-7.json"
    assert p.package_base == tmp_path / "export" / "montagem" / "7"
    assert shorts_manifest_in(p.shorts_dir, 7) == p.shorts_manifest
    assert thumbnails_in(p.packaging_dir) == p.thumbnails_dir


def test_no_module_builds_session_folders_by_hand() -> None:
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "cronista"
    pattern = re.compile(r'"(story|packaging|shorts|montagem|acabamento)" */')
    offenders = [
        p.relative_to(src).as_posix()
        for p in src.rglob("*.py")
        if p.name != "paths.py"
        and "devtools" not in p.parts
        and pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []

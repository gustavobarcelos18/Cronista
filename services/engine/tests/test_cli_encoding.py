"""A CLI não pode quebrar em console cp1252 (Windows) por causa de `→` no texto de ajuda."""

from __future__ import annotations

import os
import subprocess
import sys


def test_help_funciona_com_console_cp1252() -> None:
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}
    result = subprocess.run(
        [sys.executable, "-c", "from cronista.cli import app; app(['--help'])"],
        capture_output=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert "UnicodeEncodeError" not in result.stderr.decode("utf-8", errors="replace")
    assert "timeline do Resolve" in result.stdout.decode("utf-8", errors="replace")

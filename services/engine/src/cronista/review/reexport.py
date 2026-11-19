"""Re-exportar a montagem a partir do Studio (Fase 7C).

Usa o mesmo `export_montagem` do CLI: o cache por hash da entrada (plano + roteiro) decide o que refazer. Se
nenhuma decisão nem edição mudou o plano, o resultado é a versão anterior reaproveitada (`reused`). Roda numa
thread, uma por sessão; o Studio consulta o estado.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel

from cronista.config import Settings
from cronista.db.models import RecordingSession
from cronista.db.session import open_db
from cronista.export.pacote import export_montagem
from cronista.finishing.loader import StyleLoader
from cronista.finishing.overrides import current_item_decisions, current_settings, with_overrides
from cronista.gates import build_gate
from cronista.paths import SessionPaths
from cronista.story.script import load_script

ProfileLoader = Callable[[], tuple[list[str], list[str]]]
"""Devolve `(objetivos, regras)` do perfil; injetado pela CLI, porque só ela conhece perfis."""

State = Literal["idle", "running", "done", "error"]


class ExportStatus(BaseModel):
    """Estado da re-exportação de uma sessão; é também o contrato da API (`/sessions/{id}/export`)."""

    state: State = "idle"
    message: str = ""
    version: int | None = None
    reused: bool = False
    directory: str | None = None
    problems: list[str] = []
    warnings: list[str] = []


class ReexportJobs:
    def __init__(
        self,
        settings: Settings,
        profile_loader: ProfileLoader | None = None,
        finishing_loader: StyleLoader | None = None,
    ) -> None:
        self._settings = settings
        self._finishing = finishing_loader
        self._profile = profile_loader or (lambda: ([], []))
        self._status: dict[tuple[int, bool], ExportStatus] = {}
        self._lock = threading.Lock()
        self.last_thread: threading.Thread | None = None

    def status(self, session_id: int, series: bool = False) -> ExportStatus:
        with self._lock:
            return self._status.get((session_id, series), ExportStatus())

    def start(self, session_id: int, target_s: float, series: bool = False) -> bool:
        """Dispara a exportação; `False` se já há uma rodando para a sessão (ou para o vídeo da série).

        Com `series`, `session_id` é a sessão âncora e a montagem cobre todas as sessões do projeto.
        """
        key = (session_id, series)
        with self._lock:
            if self._status.get(key, ExportStatus()).state == "running":
                return False
            self._status[key] = ExportStatus(state="running", message="exportando…")
        self.last_thread = threading.Thread(
            target=self._run, args=(session_id, target_s, series), daemon=True
        )
        self.last_thread.start()
        return True

    def _run(self, session_id: int, target_s: float, series: bool = False) -> None:
        s = self._settings
        try:
            objetivos, regras = self._profile()
            script_path = SessionPaths.of(s, session_id).script
            script = load_script(script_path) if script_path.is_file() else None
            loaded = self._finishing() if self._finishing else None
            with open_db(s.db_path) as db:
                style = library = decisions = None
                session = db.get(RecordingSession, session_id)
                assert session is not None
                if (
                    loaded is not None
                ):  # acabamento configurado: ajustes e decisões do Studio entram no pacote
                    style = with_overrides(loaded[0], current_settings(db, session.project_id))
                    library, decisions = loaded[1], current_item_decisions(db, session_id)
                report = export_montagem(
                    db,
                    None if series else session_id,
                    s,
                    script,
                    target_s,
                    (objetivos, regras),
                    None,
                    build_gate(s),
                    style,
                    library,
                    decisions,
                    project_id=session.project_id if series else None,
                )
            result = ExportStatus(
                state="done",
                message="nada mudou: versão anterior reaproveitada" if report.reused else "versão gerada",
                version=report.version,
                reused=report.reused,
                directory=str(report.directory),
                problems=report.problems,
                warnings=report.warnings,
            )
        except Exception as exc:  # o job nunca derruba a API; o erro volta no estado
            result = ExportStatus(state="error", message=str(exc))
        with self._lock:
            self._status[(session_id, series)] = result

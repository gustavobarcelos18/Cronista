"""`cronista export <sessão>`: grava a timeline da sessão como `.otio` e `.fcpxml` para o Resolve."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import opentimelineio as otio
from sqlalchemy.orm import Session

from cronista.config import Settings
from cronista.export.fcpxml import check_fcpxml, render_fcpxml
from cronista.export.timeline import build_timeline
from cronista.logging_setup import log_event
from cronista.montage import plan_session


@dataclass
class ExportReport:
    otio_path: Path
    fcpxml_path: Path
    clips: int
    duration_s: float
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def export_session(
    db: Session, session_id: int, settings: Settings, out_dir: Path | None = None
) -> ExportReport:
    plan = plan_session(db, session_id, settings)
    timeline = build_timeline(plan, f"sessao-{session_id}")

    target = out_dir or settings.data_dir / "export"
    target.mkdir(parents=True, exist_ok=True)
    otio_path = target / f"sessao-{session_id}.otio"
    fcpxml_path = target / f"sessao-{session_id}.fcpxml"

    otio.adapters.write_to_file(timeline, str(otio_path))
    xml = render_fcpxml(timeline)
    fcpxml_path.write_text(xml, encoding="utf-8")

    video = next(t for t in timeline.tracks if t.kind == otio.schema.TrackKind.Video)
    duration = timeline.duration().to_seconds()
    log_event("exportacao_gerada", session_id=session_id, clips=len(video), path=str(fcpxml_path))
    return ExportReport(otio_path, fcpxml_path, len(video), duration, check_fcpxml(xml), plan.warnings)

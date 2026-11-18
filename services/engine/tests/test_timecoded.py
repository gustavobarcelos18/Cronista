"""Verdade-terreno do tempo dos marcadores: o quadro no tempo reconstruído mostra o relógio do toque.

Critério da 1B: erro < 100 ms nos sintéticos. O vídeo traz o relógio de parede em cada quadro (ver
`devtools.timecoded`); o diário diz a que relógio de parede cada toque aconteceu. O tempo de mídia que a
ingestão reconstrói precisa cair no quadro que mostra esse mesmo relógio, mesmo com pausa, divisão de arquivo
e gravação interrompida. Isso verifica o resultado no vídeo, não só a conta.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.config import Settings
from cronista.db.models import Marker, MediaFile
from cronista.devtools.timecoded import make_timecoded, wall_time_at
from cronista.domain.frames import frame_to_seconds
from cronista.domain.models import MarkerKind
from cronista.ingest.journal import JournalWriter, Stamp
from cronista.ingest.service import IngestReport, ingest_folder
from cronista.montage import load_source
from cronista.pipeline import AlwaysFreeGate
from tests.conftest import needs_ffmpeg

pytestmark = needs_ffmpeg

TOLERANCE_S = 0.1  # critério de aceite da 1B
BASE_MONO = 100.0


def at(wall: float) -> Stamp:
    """Instante de relógio de parede `wall` (segundos desde o início da gravação)."""
    return Stamp(BASE_MONO + wall, datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC))


@dataclass(frozen=True)
class Press:
    kind: MarkerKind
    marker_id: str
    wall: float  # relógio de parede do toque
    file: str  # arquivo em que o toque deve cair


def check_presses(
    db: Session, settings: Settings, report: IngestReport, presses: list[Press]
) -> dict[str, float]:
    """Para cada toque: o quadro no tempo de mídia reconstruído mostra o relógio do toque (erro < 100 ms)."""
    rows = {m.marker_id: m for m in db.scalars(select(Marker).where(Marker.session_id == report.session_id))}
    errors: dict[str, float] = {}
    for press in presses:
        marker = rows[press.marker_id]
        assert marker.media_file_id is not None
        media = db.get(MediaFile, marker.media_file_id)
        assert media is not None
        assert Path(media.path).name == press.file, f"{press.marker_id}: caiu em {Path(media.path).name}"
        shown = wall_time_at(settings, load_source(db, media).master, frame_to_seconds(marker.media_frame))
        errors[press.marker_id] = abs(shown - press.wall)
        assert errors[press.marker_id] < TOLERANCE_S, (
            f"{press.marker_id}: toque às {press.wall:.2f}s, quadro mostra {shown:.3f}s "
            f"(quadro de mídia {marker.media_frame})"
        )
    return errors


def test_simple_recording(db: Session, settings: Settings, tmp_path: Path) -> None:
    make_timecoded(settings, tmp_path / "jogo.mp4", [(0, 14)])
    with JournalWriter(tmp_path / "g.markers.jsonl") as w:
        w.recording_started("jogo.mp4", at(0))
        w.marker(MarkerKind.NOVO_DIA, "d1", at(0.5))
        w.marker(MarkerKind.MOMENTO, "a", at(3.2))
        w.marker(MarkerKind.ENGRACADO, "b", at(10.7))
        w.recording_stopped(at(14))

    report = ingest_folder(db, tmp_path, settings, AlwaysFreeGate(), "p")
    assert report.ok and report.markers.warnings == []
    check_presses(
        db, settings, report,
        [Press(MarkerKind.NOVO_DIA, "d1", 0.5, "jogo.mp4"), Press(MarkerKind.MOMENTO, "a", 3.2, "jogo.mp4"),
         Press(MarkerKind.ENGRACADO, "b", 10.7, "jogo.mp4")],
    )  # fmt: skip


def test_pause_is_cut_out_of_the_file_and_discounted(db: Session, settings: Settings, tmp_path: Path) -> None:
    # Gravou 0-4 s, pausou até 9 s, gravou até 14 s: o arquivo tem 9 s e o toque às 11,4 s cai em 6,4 s.
    make_timecoded(settings, tmp_path / "jogo.mp4", [(0, 4), (9, 14)])
    with JournalWriter(tmp_path / "g.markers.jsonl") as w:
        w.recording_started("jogo.mp4", at(0))
        w.marker(MarkerKind.NOVO_DIA, "d1", at(0.5))
        w.marker(MarkerKind.MOMENTO, "antes", at(2.3))
        w.paused(at(4))
        w.unpaused(at(9))
        w.marker(MarkerKind.MOMENTO, "logo-depois", at(9.5))
        w.marker(MarkerKind.CONQUISTA, "depois", at(11.4))
        w.recording_stopped(at(14))

    report = ingest_folder(db, tmp_path, settings, AlwaysFreeGate(), "p")
    assert report.ok and report.markers.warnings == []
    errors = check_presses(
        db, settings, report,
        [Press(MarkerKind.NOVO_DIA, "d1", 0.5, "jogo.mp4"),
         Press(MarkerKind.MOMENTO, "antes", 2.3, "jogo.mp4"),
         Press(MarkerKind.MOMENTO, "logo-depois", 9.5, "jogo.mp4"),
         Press(MarkerKind.CONQUISTA, "depois", 11.4, "jogo.mp4")],
    )  # fmt: skip
    media_times = {
        m.marker_id: m.media_frame for m in db.scalars(select(Marker).where(Marker.marker_id == "depois"))
    }
    assert media_times["depois"] == pytest.approx(384, abs=1)  # e não 11,4, que passa do fim do arquivo
    assert max(errors.values()) < TOLERANCE_S


def test_file_split_restarts_the_clock_in_the_new_file(
    db: Session, settings: Settings, tmp_path: Path
) -> None:
    make_timecoded(settings, tmp_path / "g1.mp4", [(0, 6)])
    make_timecoded(settings, tmp_path / "g2.mp4", [(6, 12)])
    with JournalWriter(tmp_path / "g.markers.jsonl") as w:
        w.recording_started("g1.mp4", at(0))
        w.marker(MarkerKind.NOVO_DIA, "d1", at(0.5))
        w.marker(MarkerKind.MOMENTO, "no-1", at(4.1))
        w.file_changed("g2.mp4", at(6))
        w.marker(MarkerKind.MOMENTO, "no-2", at(8.35))
        w.recording_stopped(at(12))

    report = ingest_folder(db, tmp_path, settings, AlwaysFreeGate(), "p")
    assert report.ok and report.markers.warnings == []
    check_presses(
        db, settings, report,
        [Press(MarkerKind.NOVO_DIA, "d1", 0.5, "g1.mp4"), Press(MarkerKind.MOMENTO, "no-1", 4.1, "g1.mp4"),
         Press(MarkerKind.MOMENTO, "no-2", 8.35, "g2.mp4")],
    )  # fmt: skip


def test_pause_in_the_first_file_does_not_leak_into_the_second(
    db: Session, settings: Settings, tmp_path: Path
) -> None:
    # g1 = relógio 0-4 e 9-12 (pausa de 5 s); a divisão ocorre às 12 s; g2 = 12-16.
    make_timecoded(settings, tmp_path / "g1.mp4", [(0, 4), (9, 12)])
    make_timecoded(settings, tmp_path / "g2.mp4", [(12, 16)])
    with JournalWriter(tmp_path / "g.markers.jsonl") as w:
        w.recording_started("g1.mp4", at(0))
        w.marker(MarkerKind.NOVO_DIA, "d1", at(0.5))
        w.paused(at(4))
        w.unpaused(at(9))
        w.marker(MarkerKind.MOMENTO, "g1-depois-pausa", at(10.5))
        w.file_changed("g2.mp4", at(12))
        w.marker(MarkerKind.MOMENTO, "g2", at(14.0))
        w.recording_stopped(at(16))

    report = ingest_folder(db, tmp_path, settings, AlwaysFreeGate(), "p")
    assert report.ok and report.markers.warnings == []
    check_presses(
        db, settings, report,
        [Press(MarkerKind.NOVO_DIA, "d1", 0.5, "g1.mp4"),
         Press(MarkerKind.MOMENTO, "g1-depois-pausa", 10.5, "g1.mp4"),
         Press(MarkerKind.MOMENTO, "g2", 14.0, "g2.mp4")],
    )  # fmt: skip


def test_interrupted_recording_after_remux(db: Session, settings: Settings, tmp_path: Path) -> None:
    # Queda: arquivo fragmentado e cortado, diário sem `recording_stopped`. O remux da ingestão recupera o
    # que foi gravado e os toques que cabem no arquivo seguem corretos.
    make_timecoded(settings, tmp_path / "queda.mp4", [(0, 14)], interrupted=True)
    with JournalWriter(tmp_path / "g.markers.jsonl") as w:
        w.recording_started("queda.mp4", at(0))
        w.marker(MarkerKind.NOVO_DIA, "d1", at(0.5))
        w.marker(MarkerKind.MOMENTO, "a", at(3.3))
        w.marker(MarkerKind.MORTE_FALHA, "b", at(9.0))

    report = ingest_folder(db, tmp_path, settings, AlwaysFreeGate(), "p")
    assert report.ok
    normalize = next(iter(report.files.values())).results["normalize"]
    assert normalize.data["actions"] == ["remux"]
    check_presses(
        db, settings, report,
        [Press(MarkerKind.NOVO_DIA, "d1", 0.5, "queda.mp4"), Press(MarkerKind.MOMENTO, "a", 3.3, "queda.mp4"),
         Press(MarkerKind.MORTE_FALHA, "b", 9.0, "queda.mp4")],
    )  # fmt: skip


def test_the_oracle_distinguishes_wall_clock_from_file_time(settings: Settings, tmp_path: Path) -> None:
    """Controle negativo: após a pausa, o quadro mostra o relógio de parede, e não o tempo de arquivo."""
    make_timecoded(settings, tmp_path / "jogo.mp4", [(0, 4), (9, 14)])
    # O toque às 11,4 s sem descontar os 5 s de pausa daria 11,4 s de mídia, além dos 9 s do arquivo;
    # num instante que existe (6,4 s), o relógio mostrado é 11,4 s, e não 6,4 s.
    shown = wall_time_at(settings, tmp_path / "jogo.mp4", 6.4)
    assert shown == pytest.approx(11.4, abs=TOLERANCE_S)
    assert abs(shown - 6.4) > 4.0

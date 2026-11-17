"""Tabela de B-roll do relatório: colunas alinhadas com o cabeçalho e texto escapado."""

from __future__ import annotations

from cronista.audio.events import StoredEvent
from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource
from cronista.video.report import broll_table


def _broll(tags: list[str]) -> StoredEvent:
    ev = Evidence(
        source=EvidenceSource.CENA,
        start_frame=600,
        end_frame=1200,
        confidence=0.74,
        model="m",
        model_version="1",
        params_hash="h",
    )
    payload = {"movimento": "parada", "clima": "sombrio", "hud": "oculto", "tags": tags}
    return StoredEvent("video_broll", "", AnalysisEvent(kind="broll", evidence=ev, payload=payload))


def test_broll_rows_have_one_cell_per_header() -> None:
    html = broll_table([_broll(["a cave"])], None, None)
    header = html.split("<tr>")[1]
    row = html.split("<tr>")[2]
    assert header.count("<th>") == row.count("<td") == 8
    assert "sombrio" in row and "oculto" in row and "0.74" in row


def test_broll_text_is_escaped() -> None:
    html = broll_table([_broll(["<script>x</script>", "a&b"])], None, None)
    assert "<script>" not in html and "&lt;script&gt;" in html and "a&amp;b" in html

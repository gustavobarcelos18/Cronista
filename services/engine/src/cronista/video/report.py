"""Seção de vídeo do relatório HTML: estados de tela, sinais visuais e miniaturas dos trechos (Fase 3A).

Miniaturas são JPEG pequenos embutidos no HTML (data URI), tirados do proxy com o FFmpeg; sem `settings`
não há miniaturas. Todo texto passa por `html.escape`.
"""

from __future__ import annotations

import base64
import html
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cronista.audio.events import StoredEvent
from cronista.audio.report import CHART_W, PAD_B, PAD_L, PAD_T, _axis, _x, fmt_time, line_chart
from cronista.audio.signals import Signal
from cronista.config import Settings
from cronista.db.models import Marker
from cronista.domain.frames import FPS

VIDEO_STAGES = ("video_signals", "video_scenes", "video_contexts", "video_broll")
STATE_KINDS = ("loading", "menu", "idle")
THUMBS_PER_KIND = 6
THUMB_WIDTH = 320

CHARTS: tuple[tuple[str, str, tuple[float, float] | None], ...] = (
    ("video.motion", "Vídeo: movimento entre quadros", (0.0, 0.5)),
    ("video.still", "Vídeo: fração da tela parada", (0.0, 1.0)),
    ("video.edge_density", "Vídeo: densidade de bordas (menus têm muita)", (0.0, 1.0)),
    ("video.luma_mean", "Vídeo: brilho médio", (0.0, 1.0)),
)

CONTEXT_COLORS = ("#2563eb", "#16a34a", "#d97706", "#dc2626", "#7c3aed", "#0891b2", "#be185d", "#65a30d")

LANE_COLORS = {
    "loading": "#dc2626",
    "menu": "#2563eb",
    "idle": "#d97706",
    "movimento_camera": "#16a34a",
    "cena": "#7c3aed",
}


def is_video_event(stored: StoredEvent) -> bool:
    return stored.stage in VIDEO_STAGES


def thumbnail(settings: Settings, proxy: Path, frame: int) -> str | None:
    """JPEG do quadro `frame` (60 fps) em data URI, ou `None` se o FFmpeg não conseguir."""
    cmd = [
        settings.ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{frame / FPS:.2f}", "-i", str(proxy),
        "-frames:v", "1", "-vf", f"scale={THUMB_WIDTH}:-2", "-f", "image2pipe", "-c:v", "mjpeg", "-",
    ]  # fmt: skip
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    return "data:image/jpeg;base64," + base64.b64encode(proc.stdout).decode("ascii")


def state_lanes(events: list[StoredEvent], markers: list[Marker], total_frames: int) -> str:
    kinds = [
        k
        for k in (*STATE_KINDS, "movimento_camera", "cena", "contexto")
        if any(e.event.kind == k for e in events)
    ]
    if not kinds:
        return '<h3>Estados de tela</h3><p class="muted">Nenhum estado de tela detectado.</p>'
    lane_h = 16
    height = PAD_T + PAD_B + lane_h * len(kinds)
    rows: list[str] = []
    for row, kind in enumerate(kinds):
        y = PAD_T + row * lane_h
        rows.append(
            f'<text x="{PAD_L - 6}" y="{y + 12}" font-size="10" fill="var(--muted)" text-anchor="end">'
            f"{html.escape(kind)}</text>"
        )
        drawn: set[int] = set()  # cortes de cena são muitos: um retângulo por pixel de largura basta
        for stored in (e for e in events if e.event.kind == kind):
            ev = stored.event.evidence
            x0, x1 = _x(ev.start_frame, total_frames), _x(ev.end_frame, total_frames)
            if kind == "cena":
                if round(x0) in drawn:
                    continue
                drawn.add(round(x0))
            detail = stored.event.payload.get("tipo", "")
            tip = html.escape(
                f"{kind} {detail} {fmt_time(ev.start_frame)} a {fmt_time(ev.end_frame)}".replace("  ", " ")
            )
            color = LANE_COLORS.get(kind, "#7c3aed")
            if kind == "contexto":
                cid = int(stored.event.payload.get("context_id", 0))
                color = CONTEXT_COLORS[cid % len(CONTEXT_COLORS)]
                tip = html.escape(f"contexto {cid} {fmt_time(ev.start_frame)} a {fmt_time(ev.end_frame)}")
            rows.append(
                f'<rect x="{x0:.1f}" y="{y + 2}" width="{max(x1 - x0, 2):.1f}" height="{lane_h - 4}" '
                f'fill="{color}"><title>{tip}</title></rect>'
            )
    marks = "".join(
        f'<line x1="{_x(m.media_frame, total_frames):.1f}" x2="{_x(m.media_frame, total_frames):.1f}" '
        f'y1="{PAD_T}" y2="{height - PAD_B}" stroke="var(--mark)" stroke-dasharray="3 3"/>'
        for m in markers
    )
    return (
        f'<h3>Estados de tela</h3><svg viewBox="0 0 {CHART_W} {height}" role="img" '
        'aria-label="Estados de tela">'
        f"<title>Estados de tela</title>{_axis(total_frames, height)}{''.join(rows)}{marks}</svg>"
    )


def state_table(events: list[StoredEvent], settings: Settings | None, proxy: Path | None) -> str:
    """Tabela dos trechos de loading/menu/idle (os mais longos primeiro), com miniatura do meio de cada um."""
    parts: list[str] = []
    for kind in STATE_KINDS:
        items = sorted(
            (e for e in events if e.event.kind == kind),
            key=lambda e: e.event.evidence.end_frame - e.event.evidence.start_frame,
            reverse=True,
        )
        if not items:
            continue
        shown = items[:THUMBS_PER_KIND]
        rows = []
        ordered = sorted(shown, key=lambda e: e.event.evidence.start_frame)
        thumbs: list[str | None] = [None] * len(ordered)
        if settings is not None and proxy is not None and proxy.is_file():
            with ThreadPoolExecutor(max_workers=4) as pool:  # um ffmpeg por miniatura, em paralelo
                thumbs = list(
                    pool.map(
                        lambda e: thumbnail(
                            settings, proxy, (e.event.evidence.start_frame + e.event.evidence.end_frame) // 2
                        ),
                        ordered,
                    )
                )
        for stored, data in zip(ordered, thumbs, strict=True):
            ev = stored.event.evidence
            seconds = (ev.end_frame - ev.start_frame) / FPS
            image = ""
            if data:
                alt = html.escape(f"{kind} em {fmt_time(ev.start_frame)}")
                image = f'<img src="{data}" alt="{alt}" width="160">'
            rows.append(
                f'<tr><td class="num">{fmt_time(ev.start_frame)}</td><td class="num">{seconds:.0f} s</td>'
                f'<td class="num">{ev.confidence:.2f}</td><td>{image}</td></tr>'
            )
        extra = f" (mostrando os {len(shown)} mais longos de {len(items)})" if len(items) > len(shown) else ""
        total_min = sum(e.event.evidence.end_frame - e.event.evidence.start_frame for e in items) / FPS / 60
        parts.append(
            f"<h3>{html.escape(kind)}: {len(items)} trechos, {total_min:.1f} min no total{extra}</h3>"
            f"<table><tr><th>Início</th><th>Duração</th><th>Conf.</th><th>Quadro do meio</th></tr>"
            f"{''.join(rows)}</table>"
        )
    return "".join(parts)


def context_table(events: list[StoredEvent], settings: Settings | None, proxy: Path | None) -> str:
    """Mapa de contextos visuais: tempo total e quadro representativo de cada um (maiores primeiro)."""
    totals: dict[int, int] = {}
    reps: dict[int, int] = {}
    for stored in events:
        if stored.event.kind != "contexto":
            continue
        cid = int(stored.event.payload.get("context_id", 0))
        ev = stored.event.evidence
        totals[cid] = totals.get(cid, 0) + ev.end_frame - ev.start_frame
        reps.setdefault(cid, int(stored.event.payload.get("representative_frame", ev.start_frame)))
    if not totals:
        return ""
    order = sorted(totals, key=lambda c: totals[c], reverse=True)
    thumbs: list[str | None] = [None] * len(order)
    if settings is not None and proxy is not None and proxy.is_file():
        with ThreadPoolExecutor(max_workers=4) as pool:
            thumbs = list(pool.map(lambda c: thumbnail(settings, proxy, reps[c]), order))
    rows = []
    for cid, data in zip(order, thumbs, strict=True):
        image = f'<img src="{data}" alt="contexto {cid}" width="160">' if data else ""
        color = CONTEXT_COLORS[cid % len(CONTEXT_COLORS)]
        rows.append(
            f'<tr><td><span style="color:{color}">&#9632;</span> {cid}</td>'
            f'<td class="num">{totals[cid] / FPS / 60:.1f} min</td><td>{image}</td></tr>'
        )
    return (
        f"<h3>Contextos visuais: {len(order)}</h3>"
        "<table><tr><th>Contexto</th><th>Tempo total</th><th>Quadro representativo</th></tr>"
        f"{''.join(rows)}</table>"
    )


def broll_table(
    events: list[StoredEvent], settings: Settings | None, proxy: Path | None, top: int = 12
) -> str:
    """Galeria de B-roll candidato: os de maior nota de beleza, com capa, movimento e tags."""
    clips = sorted(
        (e.event for e in events if e.event.kind == "broll"),
        key=lambda e: e.evidence.confidence,
        reverse=True,
    )[:top]
    if not clips:
        return ""
    thumbs: list[str | None] = [None] * len(clips)
    if settings is not None and proxy is not None and proxy.is_file():
        with ThreadPoolExecutor(max_workers=4) as pool:
            thumbs = list(
                pool.map(
                    lambda e: thumbnail(
                        settings, proxy, int(e.payload.get("cover_frame", e.evidence.start_frame))
                    ),
                    clips,
                )
            )
    rows = []
    for ev, data in zip(clips, thumbs, strict=True):
        image = f'<img src="{data}" alt="B-roll" width="160">' if data else ""
        tags = ", ".join(str(t) for t in ev.payload.get("tags", []))
        rows.append(
            f'<tr><td class="num">{ev.evidence.start_frame / FPS:.0f} s</td>'
            f'<td class="num">{(ev.evidence.end_frame - ev.evidence.start_frame) / FPS:.0f} s</td>'
            f'<td>{ev.payload.get("movimento", "")}</td><td class="num">{ev.evidence.confidence:.2f}</td>'
            f"<td>{tags}</td><td>{image}</td></tr>"
        )
    return (
        f"<h3>B-roll candidato: {len(clips)} melhores</h3>"
        "<table><tr><th>Início</th><th>Duração</th><th>Movimento</th><th>Beleza</th><th>Tags</th>"
        f"<th>Capa</th></tr>{''.join(rows)}</table>"
    )


def video_section(
    events: list[StoredEvent],
    signals: dict[str, Signal],
    markers: list[Marker],
    total_frames: int,
    settings: Settings | None = None,
    proxy: Path | None = None,
) -> str:
    """HTML da parte de vídeo de um arquivo; vazio se a análise de vídeo não rodou."""
    if not signals and not events:
        return ""
    parts = ["<h2>Vídeo</h2>"]
    parts.append(state_lanes(events, markers, total_frames))
    for name, title, fixed in CHARTS:
        if name in signals:
            parts.append(line_chart(signals[name], title, markers, total_frames, fixed))
    parts.append(context_table(events, settings, proxy))
    parts.append(broll_table(events, settings, proxy))
    parts.append(state_table(events, settings, proxy))
    return "".join(parts)

"""Relatório HTML da sessão: sinais por tempo, marcadores, eventos e fala. Arquivo único, sem rede nem JavaScript.

Visibilidade desde cedo (plano, Fase 2): o Studio só chega na Fase 7. Todo texto vindo de fora (transcrição, caminhos,
avisos) passa por `html.escape`.
"""

from __future__ import annotations

import html
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.audio.events import StoredEvent, load_stored_events
from cronista.audio.signals import Signal, load_signal, signal_metas
from cronista.config import Settings
from cronista.db.models import Artifact, Marker, MediaFile, RecordingSession
from cronista.domain.frames import FPS
from cronista.domain.models import StageResult
from cronista.domain.types import FloatArray

CHART_W, CHART_H, PAD_L, PAD_R, PAD_T, PAD_B = 1000, 96, 56, 12, 8, 20
MAX_POINTS = 1200
TICKS_S = (10, 30, 60, 300, 600, 1800, 3600, 7200, 14400)

# nome do sinal → (título, unidade, faixa fixa do eixo ou None para automática)
CHARTS: tuple[tuple[str, str, tuple[float, float] | None], ...] = (
    ("game.novelty", "Jogo: novidade em relação à sessão", None),
    ("game.novelty_ctx", "Jogo: novidade em relação ao contexto visual", None),
    ("game.periodicity", "Jogo: periodicidade (rotina)", (0.0, 1.0)),
    ("game.energy_db", "Jogo: energia (dBFS)", None),
    ("mic.energy_db", "Microfone: energia (dBFS)", None),
    ("mic.energy_rel_db", "Microfone: dB acima da mediana da sessão", None),
)

CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--muted:#667;--line:#2563eb;--grid:#d8dce3;--card:#f6f7f9;--mark:#b45309;
--fala:#16a34a;--risada:#d97706;--grito:#dc2626;--other:#7c3aed}
@media (prefers-color-scheme:dark){:root{--bg:#14161a;--fg:#e6e8eb;--muted:#9aa3ad;--line:#60a5fa;--grid:#2c313a;
--card:#1d2026;--mark:#fbbf24;--fala:#4ade80;--risada:#fbbf24;--grito:#f87171;--other:#a78bfa}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:1060px;padding:16px}
h1{font-size:1.4rem}h2{font-size:1.15rem;margin-top:2rem}h3{font-size:.95rem;margin:1rem 0 .2rem;color:var(--muted)}
.card{background:var(--card);border-radius:8px;padding:8px 12px;margin:.5rem 0}
svg{width:100%;height:auto;display:block}table{border-collapse:collapse;width:100%}
td,th{text-align:left;padding:3px 8px;border-bottom:1px solid var(--grid);vertical-align:top;font-size:.9rem}
.num{white-space:nowrap;font-variant-numeric:tabular-nums}.warn{color:var(--mark)}.muted{color:var(--muted)}
"""


def fmt_time(frame: int) -> str:
    seconds = frame // FPS
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def downsample(values: FloatArray, limit: int = MAX_POINTS) -> tuple[FloatArray, int]:
    """Reduz a série ao teto de pontos guardando o máximo de cada grupo (picos não podem sumir)."""
    values = np.asarray(values, dtype=np.float32)
    if len(values) <= limit:
        return values, 1
    group = -(-len(values) // limit)
    padding = np.full((-len(values)) % group, -np.inf, dtype=np.float32)  # completa o último grupo
    return np.concatenate([values, padding]).reshape(-1, group).max(axis=1), group


def _event_class(kind: str) -> str:
    return "grito" if kind == "exclamacao" else kind if kind in ("fala", "risada", "grito") else "other"


def _ticks(total_frames: int) -> list[int]:
    total_s = max(total_frames / FPS, 1)
    step = next((t for t in TICKS_S if total_s / t <= 10), TICKS_S[-1])
    return [s * FPS for s in range(0, int(total_s) + 1, step)]


def _x(frame: float, total_frames: int) -> float:
    return PAD_L + (CHART_W - PAD_L - PAD_R) * (frame / max(total_frames, 1))


def _axis(total_frames: int, height: int) -> str:
    parts = []
    for frame in _ticks(total_frames):
        x = _x(frame, total_frames)
        parts.append(
            f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{PAD_T}" y2="{height - PAD_B}" stroke="var(--grid)"/>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{height - 6}" font-size="10" fill="var(--muted)" text-anchor="middle">'
            f"{fmt_time(frame)}</text>"
        )
    return "".join(parts)


def _markers(markers: list[Marker], total_frames: int, height: int) -> str:
    out = []
    for m in markers:
        x = _x(m.media_frame, total_frames)
        out.append(
            f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{PAD_T}" y2="{height - PAD_B}" stroke="var(--mark)" '
            f'stroke-dasharray="3 3"><title>{html.escape(m.kind)} em {fmt_time(m.media_frame)}</title></line>'
        )
    return "".join(out)


def line_chart(
    signal: Signal, title: str, markers: list[Marker], total_frames: int, fixed: tuple[float, float] | None
) -> str:
    values, group = downsample(np.asarray(signal.values))
    if len(values) == 0:
        return f'<p class="muted">{html.escape(title)}: sem dados.</p>'
    # Sem faixa fixa, o piso é o percentil 0,5: um trecho de silêncio digital (-120 dB) não estica o eixo todo.
    low, high = fixed if fixed else (float(np.percentile(values, 0.5)), float(values.max()))
    if high - low < 1e-6:
        high = low + 1.0
    plot_h = CHART_H - PAD_T - PAD_B
    step = signal.meta.hop_frames * group
    points = " ".join(
        f"{_x(i * step, total_frames):.1f},{PAD_T + plot_h * (1 - min(max((float(v) - low) / (high - low), 0.0), 1.0)):.1f}"
        for i, v in enumerate(values)
    )
    label = html.escape(title)
    return (
        f'<h3>{label}</h3><svg viewBox="0 0 {CHART_W} {CHART_H}" role="img" aria-label="{label}">'
        f"<title>{label}</title>{_axis(total_frames, CHART_H)}"
        f'<text x="{PAD_L - 6}" y="{PAD_T + 8}" font-size="10" fill="var(--muted)" text-anchor="end">{high:.3g}</text>'
        f'<text x="{PAD_L - 6}" y="{CHART_H - PAD_B}" font-size="10" fill="var(--muted)" text-anchor="end">{low:.3g}</text>'
        f'<polyline points="{points}" fill="none" stroke="var(--line)" stroke-width="1.2"/>'
        f"{_markers(markers, total_frames, CHART_H)}</svg>"
    )


def _lane_names(events: list[StoredEvent]) -> dict[int, str]:
    """Nome da faixa de cada evento: o tipo; com mais de um produtor para o mesmo tipo, `tipo (produtor)`."""
    producers: dict[str, set[str]] = {}
    for stored in events:
        producers.setdefault(stored.event.kind, set()).add(stored.producer)
    return {
        i: stored.event.kind
        if len(producers[stored.event.kind]) == 1
        else f"{stored.event.kind} ({stored.producer})"
        for i, stored in enumerate(events)
    }


def event_lanes(events: list[StoredEvent], markers: list[Marker], total_frames: int) -> str:
    names = _lane_names(events)
    lanes = sorted(set(names.values()))
    if not lanes:
        return '<p class="muted">Nenhum evento de áudio gravado (sem modelos nesta máquina ou nada detectado).</p>'
    lane_h = 16
    height = PAD_T + PAD_B + lane_h * len(lanes)
    rows = []
    for row, lane in enumerate(lanes):
        y = PAD_T + row * lane_h
        rows.append(
            f'<text x="{PAD_L - 6}" y="{y + 12}" font-size="10" fill="var(--muted)" text-anchor="end">{html.escape(lane)}</text>'
        )
        for i in (i for i, name in names.items() if name == lane):
            e = events[i].event
            kind = e.kind
            ev = e.evidence
            x0, x1 = _x(ev.start_frame, total_frames), _x(ev.end_frame, total_frames)
            quote = f": {ev.quote[:80]}" if ev.quote else ""
            tip = html.escape(f"{kind} {fmt_time(ev.start_frame)} a {fmt_time(ev.end_frame)}{quote}")
            rows.append(
                f'<rect x="{x0:.1f}" y="{y + 2}" width="{max(x1 - x0, 2):.1f}" height="{lane_h - 4}" '
                f'fill="var(--{_event_class(kind)})"><title>{tip}</title></rect>'
            )
    return (
        f'<h3>Eventos</h3><svg viewBox="0 0 {CHART_W} {height}" role="img" aria-label="Eventos de áudio">'
        f"<title>Eventos de áudio</title>{_axis(total_frames, height)}{''.join(rows)}"
        f"{_markers(markers, total_frames, height)}</svg>"
    )


def _result_of(db: Session, media: MediaFile, stage: str, variant: str = "") -> StageResult | None:
    artifact = db.scalar(
        select(Artifact).where(
            Artifact.media_file_id == media.id, Artifact.stage == stage, Artifact.variant == variant
        )
    )
    path = Path(artifact.result_path) if artifact else None
    if path is None or not path.is_file():
        return None
    return StageResult.model_validate_json(path.read_text(encoding="utf-8"))


def _warnings(db: Session, media: MediaFile) -> list[str]:
    out: list[str] = []
    for artifact in db.scalars(
        select(Artifact).where(Artifact.media_file_id == media.id).order_by(Artifact.id)
    ):
        path = Path(artifact.result_path)
        if path.is_file():
            label = f"{artifact.stage}:{artifact.variant}" if artifact.variant else artifact.stage
            out += [
                f"{label}: {w}"
                for w in StageResult.model_validate_json(path.read_text(encoding="utf-8")).warnings
            ]
    return out


def _media_section(db: Session, media: MediaFile, settings: Settings | None = None) -> str:
    from cronista.video.report import is_video_event, video_section

    markers = list(
        db.scalars(select(Marker).where(Marker.media_file_id == media.id).order_by(Marker.media_frame))
    )
    all_events = load_stored_events(db, media.id)
    events = [e for e in all_events if not is_video_event(e)]
    video_events = [e for e in all_events if is_video_event(e)]
    signals: dict[str, Signal] = {}
    result = _result_of(db, media, "audio_signals")
    if result is not None:
        signals = {n: load_signal(m) for n, m in signal_metas(result).items()}
    video_signals: dict[str, Signal] = {}
    video_result = _result_of(db, media, "video_signals")
    if video_result is not None:
        video_signals = {n: load_signal(m) for n, m in signal_metas(video_result).items()}

    total = max(
        [s.end_frame for s in [*signals.values(), *video_signals.values()]]
        + [s.event.evidence.end_frame for s in all_events]
        + [m.media_frame for m in markers]
        + [1]
    )
    parts = [
        f"<h2>{html.escape(Path(media.path).name)}</h2>",
        f'<p class="muted">Duração analisada: {fmt_time(total)}</p>',
    ]
    if not signals:
        parts.append('<p class="warn">Sem sinais: rode <code>cronista analyze</code> para esta sessão.</p>')
    for name, title, fixed in CHARTS:
        if name in signals:
            parts.append(line_chart(signals[name], title, markers, total, fixed))
    parts.append(event_lanes(events, markers, total))
    proxy_result = _result_of(db, media, "proxy")
    proxy = Path(str(proxy_result.data.get("proxy", ""))) if proxy_result else None
    parts.append(video_section(video_events, video_signals, markers, total, settings, proxy))

    speech_by_producer: dict[str, list[StoredEvent]] = {}
    for stored in events:
        if stored.event.kind == "fala":
            speech_by_producer.setdefault(stored.producer, []).append(stored)
    for producer, group in speech_by_producer.items():
        suffix = f" ({html.escape(producer)})" if len(speech_by_producer) > 1 else ""
        rows = "".join(
            f'<tr><td class="num">{fmt_time(s.event.evidence.start_frame)}</td>'
            f"<td>{html.escape(s.event.evidence.quote or '')}</td>"
            f'<td class="num">{s.event.evidence.confidence:.2f}</td><td>{html.escape(s.event.evidence.model)}</td></tr>'
            for s in group
        )
        parts.append(
            f"<h3>Fala transcrita{suffix}</h3>"
            f"<table><tr><th>Início</th><th>Texto</th><th>Conf.</th><th>Modelo</th></tr>{rows}</table>"
        )
    if markers:
        rows = "".join(
            f'<tr><td class="num">{fmt_time(m.media_frame)}</td><td>{html.escape(m.kind)}</td>'
            f'<td class="warn">{html.escape(m.warning or "")}</td></tr>'
            for m in markers
        )
        parts.append(
            f"<h3>Marcadores</h3><table><tr><th>Quando</th><th>Tipo</th><th>Aviso</th></tr>{rows}</table>"
        )
    warnings = _warnings(db, media)
    if warnings:
        items = "".join(f"<li>{html.escape(w)}</li>" for w in warnings)
        parts.append(f'<h3>Avisos</h3><ul class="warn">{items}</ul>')
    return f'<section class="card">{"".join(parts)}</section>'


def render_session_report(db: Session, session_id: int, settings: Settings | None = None) -> str:
    session = db.get(RecordingSession, session_id)
    if session is None:
        raise LookupError(f"Sessão {session_id} não existe (veja `cronista status`)")
    body = "".join(_media_section(db, media, settings) for media in session.media_files)
    if not session.media_files:
        body = '<p class="muted">Sessão sem arquivos.</p>'
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Sessão {session.id}: relatório de áudio</title><style>{CSS}</style></head><body>"
        f"<h1>Sessão {session.id}: relatório de áudio</h1>"
        f'<p class="muted">Origem: {html.escape(session.folder)}. Linhas tracejadas são marcadores; '
        "passe o mouse sobre eventos e marcadores para ver os detalhes.</p>"
        f"{body}</body></html>"
    )


def write_session_report(db: Session, session_id: int, settings: Settings, out: Path | None = None) -> Path:
    page = render_session_report(db, session_id, settings)
    path = out or settings.data_dir / "reports" / f"sessao-{session_id}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path

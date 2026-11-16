"""CLI: `cronista ingest <pasta>`, `status`, `preview <sessão>`, `export <sessão>`, `fixtures`."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import select

from cronista.config import load_settings
from cronista.db.models import Job, MediaFile, Project, RecordingSession
from cronista.db.session import open_db
from cronista.devtools.fixtures import make_fixtures
from cronista.devtools.resolve_kit import make_resolve_kit
from cronista.domain.frames import frame_to_seconds
from cronista.export.service import export_session
from cronista.gabarito import validate_gabarito
from cronista.gates import build_gate
from cronista.ingest.ffmpeg import probe_media, run_ffmpeg
from cronista.ingest.service import SessionConflictError, ingest_folder
from cronista.logging_setup import setup_logging
from cronista.montage import SessionPlanError
from cronista.pipeline import recover_orphans
from cronista.preview import PreviewError, build_preview
from cronista.recorder.feedback import ConsoleFeedback
from cronista.recorder.hotkeys import HotkeyConfigError
from cronista.recorder.run import run_forever
from cronista.watch import Processed
from cronista.watch import serve as watch_serve


def _force_utf8_output() -> None:
    """Força UTF-8 na saída: o console do Windows (cp1252) quebra com `→` e caminhos acentuados raros."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


_force_utf8_output()

app = typer.Typer(help="Cronista: gameplay do OBS → timeline do Resolve.", no_args_is_help=True)


@app.command()
def ingest(
    folder: Annotated[Path, typer.Argument(help="Pasta da sessão de gravação")],
    project: Annotated[str, typer.Option(help="Nome do projeto (série)")] = "default",
) -> None:
    """Ingere uma sessão: valida, remuxa se preciso, gera proxy e WAVs. Retoma de onde parou."""
    settings = load_settings()
    setup_logging(settings.log_level)
    with open_db(settings.db_path) as db:
        recovered = recover_orphans(db)
        if recovered:
            typer.echo(f"{recovered} job(s) interrompido(s) voltaram para a fila.")
        try:
            report = ingest_folder(db, folder, settings, build_gate(settings), project)
        except (FileNotFoundError, SessionConflictError) as exc:
            typer.echo(f"erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    for path, result in report.files.items():
        typer.echo(f"{path}: executadas={result.executed} em_cache={result.cached}")
        for stage in result.results.values():
            for warning in stage.warnings:
                typer.echo(f"  aviso: {warning}")
    typer.echo(f"marcadores: {report.markers.count}")
    for warning in report.markers.warnings:
        typer.echo(f"  aviso: {warning}")
    for path, error in report.failures.items():
        typer.echo(f"FALHOU {path}: {error}", err=True)
    raise typer.Exit(0 if report.ok else 1)


@app.command()
def status() -> None:
    """Mostra projetos, sessões e o estado dos jobs."""
    settings = load_settings()
    with open_db(settings.db_path) as db:
        for project in db.scalars(select(Project)):
            typer.echo(f"Projeto {project.name}")
            for session in project.sessions:
                typer.echo(f"  Sessão {session.id}: {session.folder}")
                for media in session.media_files:
                    typer.echo(f"    {Path(media.path).name}")
                    for job in db.scalars(select(Job).where(Job.media_file_id == media.id).order_by(Job.id)):
                        extra = f" ({job.error})" if job.error else ""
                        typer.echo(f"      {job.stage}: {job.status}{extra}")
        if db.scalar(select(RecordingSession.id)) is None and db.scalar(select(MediaFile.id)) is None:
            typer.echo("Nada ingerido ainda.")


@app.command()
def preview(
    session: Annotated[int, typer.Argument(help="Número da sessão (veja `cronista status`)")],
    out: Annotated[
        Path | None, typer.Option(help="MP4 de saída (padrão: data/previews/sessao-N.mp4)")
    ] = None,
) -> None:
    """Gera o MP4 de prévia: uma janela (20 s antes, 10 s depois) por marcador, com o áudio do mix."""
    settings = load_settings()
    setup_logging(settings.log_level)
    with open_db(settings.db_path) as db:
        try:
            report = build_preview(db, session, settings, build_gate(settings), out)
        except PreviewError as exc:
            typer.echo(f"erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    actual = f"{report.actual_s:.1f}s" if report.actual_s is not None else "?"
    typer.echo(f"{report.path}: {report.clips} trecho(s), esperado {report.expected_s:.1f}s, gerado {actual}")
    for warning in report.warnings:
        typer.echo(f"  aviso: {warning}")


@app.command()
def export(
    session: Annotated[int, typer.Argument(help="Número da sessão (veja `cronista status`)")],
    out: Annotated[Path | None, typer.Option(help="Pasta de saída (padrão: data/export)")] = None,
) -> None:
    """Grava a timeline da sessão (V1 + A1/A2, 60 fps) como .fcpxml e .otio para importar no Resolve."""
    settings = load_settings()
    setup_logging(settings.log_level)
    with open_db(settings.db_path) as db:
        try:
            report = export_session(db, session, settings, out)
        except SessionPlanError as exc:
            typer.echo(f"erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"{report.fcpxml_path}: {report.clips} clipe(s), {report.duration_s:.1f}s")
    typer.echo(f"{report.otio_path}")
    for warning in report.warnings:
        typer.echo(f"  aviso: {warning}")
    for problem in report.problems:
        typer.echo(f"  validação: {problem}", err=True)
    raise typer.Exit(1 if report.problems else 0)


@app.command()
def serve(
    project: Annotated[str, typer.Option(help="Nome do projeto (série)")] = "default",
    watch: Annotated[Path | None, typer.Option(help="Pasta de gravação do OBS (padrão: watch_dir)")] = None,
    once: Annotated[bool, typer.Option("--once", help="Uma varredura e sai")] = False,
) -> None:
    """Serviço: ingere cada gravação quando ela termina (diário com recording_stopped). Ctrl+C sai."""
    settings = load_settings()
    setup_logging(settings.log_level)
    watch_dir = watch or settings.watch_dir
    if watch_dir is None or not watch_dir.is_dir():
        typer.echo("erro: defina watch_dir (config/*.local.yaml) ou use --watch com a pasta do OBS", err=True)
        raise typer.Exit(1)

    def show(item: Processed) -> None:
        if item.error:
            typer.echo(f"FALHOU {item.journal.name}: {item.error}", err=True)
        else:
            typer.echo(f"{item.journal.name}: sessão {item.session_id}, {len(item.files)} arquivo(s)")
        for warning in item.warnings:
            typer.echo(f"  aviso: {warning}")

    typer.echo(f"Observando {watch_dir} (Ctrl+C para sair)")
    with open_db(settings.db_path) as db:
        recovered = recover_orphans(db)
        if recovered:
            typer.echo(f"{recovered} job(s) interrompido(s) voltaram para a fila.")
        try:
            watch_serve(
                db, settings, build_gate(settings), watch_dir, project, show, max_scans=1 if once else None
            )
        except KeyboardInterrupt:
            typer.echo("Serviço encerrado.")


@app.command()
def record(
    quiet: Annotated[bool, typer.Option("--quiet", help="Sem sons (só mensagens)")] = False,
) -> None:
    """Gravador de marcadores: escuta as hotkeys e registra cada toque no OBS e no diário. Ctrl+C sai."""
    settings = load_settings()
    setup_logging(settings.log_level)
    feedback = ConsoleFeedback(quiet=quiet)
    try:
        asyncio.run(run_forever(settings, feedback))
    except HotkeyConfigError as exc:
        typer.echo(f"erro nas teclas: {exc}", err=True)
        raise typer.Exit(1) from exc
    except KeyboardInterrupt:
        typer.echo("Gravador encerrado.")
    finally:
        feedback.close()


@app.command()
def gabarito(
    csv_path: Annotated[Path, typer.Argument(help="CSV com inicio,fim,classe,nota")],
    video: Annotated[
        Path | None, typer.Option(help="Vídeo anotado: confere a duração e serve à prévia")
    ] = None,
    previa: Annotated[
        Path | None, typer.Option(help="Pasta onde gravar um MP4 curto por anotação, para conferir de ouvido")
    ] = None,
) -> None:
    """Valida o gabarito anotado à mão e resume o que há em cada classe (decisão D3)."""
    settings = load_settings()
    duration = None
    if video is not None:
        duration = probe_media(settings, video).duration_s
    report = validate_gabarito(csv_path, duration)
    for error in report.errors:
        typer.echo(f"erro: {error}", err=True)
    for warning in report.warnings:
        typer.echo(f"aviso: {warning}")
    for cls, (count, seconds) in report.totals().items():
        typer.echo(f"{cls:<12} {count:>4} trecho(s)  {seconds:>8.1f}s")
    if report.ok and previa is not None:
        if video is None:
            typer.echo("erro: --previa precisa de --video", err=True)
            raise typer.Exit(1)
        previa.mkdir(parents=True, exist_ok=True)
        for a in report.annotations:
            out = previa / f"{a.line:03d}-{a.cls}.mp4"
            run_ffmpeg(
                settings,
                ["-ss", f"{frame_to_seconds(a.start_frame):.3f}",
                 "-t", f"{frame_to_seconds(a.end_frame - a.start_frame):.3f}", "-i", str(video),
                 "-map", "0:v:0", "-map", "0:a:0", "-vf", "scale=640:-2,fps=30,format=yuv420p",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-c:a", "aac", str(out)],
            )  # fmt: skip
        typer.echo(f"prévia: {len(report.annotations)} arquivo(s) em {previa}")
    raise typer.Exit(0 if report.ok else 1)


@app.command("resolve-kit")
def resolve_kit(
    out: Annotated[Path | None, typer.Option(help="Pasta de saída (padrão: data/kit-resolve)")] = None,
) -> None:
    """Gera o kit de teste do Resolve gratuito (clipes, FCPXML, EDL, SRT, LUT)."""
    settings = load_settings()
    for name, path in make_resolve_kit(settings, out or settings.data_dir / "kit-resolve").items():
        typer.echo(f"{name}: {path}")


@app.command()
def fixtures(
    out: Annotated[Path | None, typer.Option(help="Pasta de saída (padrão: data/fixtures)")] = None,
) -> None:
    """Gera as fixtures sintéticas de vídeo (FFmpeg) para testar sem gravação real."""
    settings = load_settings()
    target = out or settings.data_dir / "fixtures"
    for name, path in make_fixtures(settings, target).items():
        typer.echo(f"{name}: {path}")

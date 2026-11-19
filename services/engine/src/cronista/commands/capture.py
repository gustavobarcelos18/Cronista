"""Captura, ingestão e análise de uma sessão."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import select

from cronista.audio.models import build_models
from cronista.audio.report import write_session_report
from cronista.audio.service import AnalysisError, analyze_session
from cronista.commands.common import (
    AnalysisPart,
    current_settings,
)
from cronista.db.models import Job, MediaFile, Project, RecordingSession
from cronista.db.session import open_db
from cronista.export.service import export_session
from cronista.gates import build_gate
from cronista.ingest.service import SessionConflictError, ingest_folder
from cronista.logging_setup import setup_logging
from cronista.montage import SessionPlanError
from cronista.pipeline import recover_orphans
from cronista.preview import PreviewError, build_preview
from cronista.profiles import build_models_with_profile
from cronista.recorder.feedback import ConsoleFeedback
from cronista.recorder.hotkeys import HotkeyConfigError
from cronista.recorder.run import run_forever
from cronista.watch import Processed
from cronista.watch import serve as watch_serve


def register(app: typer.Typer) -> None:
    @app.command()
    def ingest(
        folder: Annotated[Path, typer.Argument(help="Pasta da sessão de gravação")],
        project: Annotated[str, typer.Option(help="Nome do projeto (série)")] = "default",
    ) -> None:
        """Ingere uma sessão: valida, remuxa se preciso, gera proxy e WAVs. Retoma de onde parou."""
        settings = current_settings()
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
        settings = current_settings()
        with open_db(settings.db_path) as db:
            for project in db.scalars(select(Project)):
                typer.echo(f"Projeto {project.name}")
                for session in project.sessions:
                    typer.echo(f"  Sessão {session.id}: {session.folder}")
                    for media in session.media_files:
                        typer.echo(f"    {Path(media.path).name}")
                        for job in db.scalars(
                            select(Job).where(Job.media_file_id == media.id).order_by(Job.id)
                        ):
                            extra = f" ({job.error})" if job.error else ""
                            name = f"{job.stage}:{job.variant}" if job.variant else job.stage
                            typer.echo(f"      {name}: {job.status}{extra}")
            if db.scalar(select(RecordingSession.id)) is None and db.scalar(select(MediaFile.id)) is None:
                typer.echo("Nada ingerido ainda.")

    @app.command()
    def analyze(
        session: Annotated[int, typer.Argument(help="Número da sessão (veja `cronista status`)")],
        only: Annotated[
            AnalysisPart | None, typer.Option(help="`audio` ou `video` (padrão: os dois)")
        ] = None,
    ) -> None:
        """Análise da sessão: áudio (sinais, fala, eventos) e vídeo (cenas, menu, loading, idle, câmera)."""
        settings = current_settings()
        setup_logging(settings.log_level)
        try:
            video_models = build_models_with_profile(settings)
        except (FileNotFoundError, ValueError) as exc:  # perfil inexistente ou inválido
            typer.echo(f"erro: {exc}", err=True)
            raise typer.Exit(1) from exc
        with open_db(settings.db_path) as db:
            recover_orphans(db)
            try:
                report = analyze_session(
                    db,
                    session,
                    settings,
                    build_gate(settings),
                    build_models(settings),
                    only.value if only else None,
                    video_models,
                )
            except AnalysisError as exc:
                typer.echo(f"erro: {exc}", err=True)
                raise typer.Exit(1) from exc
        for name, result in report.files.items():
            typer.echo(f"{name}: executadas={result.executed} em_cache={result.cached}")
        for key, count in report.events.items():
            typer.echo(f"  eventos {key}: {count}")
        for skipped in report.skipped:
            typer.echo(f"  não rodou: {skipped}")
        for name, error in report.failures.items():
            typer.echo(f"FALHOU {name}: {error}", err=True)
        raise typer.Exit(0 if report.ok else 1)

    @app.command()
    def report(
        session: Annotated[int, typer.Argument(help="Número da sessão (veja `cronista status`)")],
        out: Annotated[
            Path | None, typer.Option(help="HTML de saída (padrão: data/reports/sessao-N.html)")
        ] = None,
    ) -> None:
        """Relatório HTML da sessão: sinais, marcadores, eventos e fala (arquivo único, abre sem rede)."""
        settings = current_settings()
        with open_db(settings.db_path) as db:
            try:
                path = write_session_report(db, session, settings, out)
            except LookupError as exc:
                typer.echo(f"erro: {exc}", err=True)
                raise typer.Exit(1) from exc
        typer.echo(str(path))

    @app.command()
    def preview(
        session: Annotated[int, typer.Argument(help="Número da sessão (veja `cronista status`)")],
        out: Annotated[
            Path | None, typer.Option(help="MP4 de saída (padrão: data/previews/sessao-N.mp4)")
        ] = None,
    ) -> None:
        """Gera o MP4 de prévia: uma janela (20 s antes, 10 s depois) por marcador, com o áudio do mix."""
        settings = current_settings()
        setup_logging(settings.log_level)
        with open_db(settings.db_path) as db:
            try:
                report = build_preview(db, session, settings, build_gate(settings), out)
            except PreviewError as exc:
                typer.echo(f"erro: {exc}", err=True)
                raise typer.Exit(1) from exc
        actual = f"{report.actual_s:.1f}s" if report.actual_s is not None else "?"
        typer.echo(
            f"{report.path}: {report.clips} trecho(s), esperado {report.expected_s:.1f}s, gerado {actual}"
        )
        for warning in report.warnings:
            typer.echo(f"  aviso: {warning}")

    @app.command(deprecated=True)
    def export(
        session: Annotated[int, typer.Argument(help="Número da sessão (veja `cronista status`)")],
        out: Annotated[Path | None, typer.Option(help="Pasta de saída (padrão: data/export)")] = None,
    ) -> None:
        """DEPRECADO (use `cronista montagem`): timeline simples da Fase 1, como .fcpxml e .otio."""
        typer.echo("aviso: `export` é da Fase 1 e foi substituído por `cronista montagem`", err=True)
        settings = current_settings()
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
        watch: Annotated[
            Path | None, typer.Option(help="Pasta de gravação do OBS (padrão: watch_dir)")
        ] = None,
        once: Annotated[bool, typer.Option("--once", help="Uma varredura e sai")] = False,
    ) -> None:
        """Serviço: ingere cada gravação quando ela termina (diário com recording_stopped). Ctrl+C sai."""
        settings = current_settings()
        setup_logging(settings.log_level)
        watch_dir = watch or settings.watch_dir
        if watch_dir is None or not watch_dir.is_dir():
            typer.echo(
                "erro: defina watch_dir (config/*.local.yaml) ou use --watch com a pasta do OBS", err=True
            )
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
                    db,
                    settings,
                    build_gate(settings),
                    watch_dir,
                    project,
                    show,
                    max_scans=1 if once else None,
                )
            except KeyboardInterrupt:
                typer.echo("Serviço encerrado.")

    @app.command()
    def record(
        quiet: Annotated[bool, typer.Option("--quiet", help="Sem sons (só mensagens)")] = False,
    ) -> None:
        """Gravador de marcadores: escuta as hotkeys e registra cada toque no OBS e no diário. Ctrl+C sai."""
        settings = current_settings()
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

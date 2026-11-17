"""CLI: `cronista ingest <pasta>`, `status`, `preview <sessão>`, `export <sessão>`, `fixtures`."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import select

from cronista.audio.models import build_models
from cronista.audio.report import write_session_report
from cronista.audio.service import AnalysisError, analyze_session
from cronista.config import load_settings
from cronista.db.models import Artifact, Job, MediaFile, Project, RecordingSession
from cronista.db.session import open_db
from cronista.devtools.fixtures import make_fixtures
from cronista.devtools.resolve_kit import make_resolve_kit
from cronista.domain.frames import frame_to_seconds
from cronista.domain.models import StageResult
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
                        name = f"{job.stage}:{job.variant}" if job.variant else job.stage
                        typer.echo(f"      {name}: {job.status}{extra}")
        if db.scalar(select(RecordingSession.id)) is None and db.scalar(select(MediaFile.id)) is None:
            typer.echo("Nada ingerido ainda.")


@app.command()
def analyze(
    session: Annotated[int, typer.Argument(help="Número da sessão (veja `cronista status`)")],
) -> None:
    """Análise de áudio da sessão: sinais de CPU e, onde houver modelos, fala e eventos sonoros."""
    settings = load_settings()
    setup_logging(settings.log_level)
    with open_db(settings.db_path) as db:
        recover_orphans(db)
        try:
            report = analyze_session(db, session, settings, build_gate(settings), build_models(settings))
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
    settings = load_settings()
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


@app.command("bench-audio")
def bench_audio(
    session: Annotated[int, typer.Argument(help="Sessão cujo primeiro arquivo serve de amostra")],
    minutes: Annotated[float, typer.Option(help="Minutos de cada faixa a medir (do início)")] = 10.0,
    file: Annotated[
        str | None, typer.Option(help="Parte do nome do arquivo (padrão: o primeiro que existe)")
    ] = None,
    out: Annotated[Path | None, typer.Option(help="JSON de saída (padrão: data/bench/audio-N.json)")] = None,
) -> None:
    """Benchmark de desempenho dos modelos de áudio (velocidade, VRAM, RAM). Qualidade é da Fase 2C."""
    from cronista.audio.bench import render_table, run_bench, write_results
    from cronista.audio.models import missing_ml_packages
    from cronista.audio.ports import GAME_TRACK, MIC_TRACK

    settings = load_settings()
    setup_logging(settings.log_level)
    models = build_models(settings)
    if models.detector is None:
        missing = missing_ml_packages()
        why = (
            f"faltam pacotes: {', '.join(missing)} (`uv sync --group ml`)"
            if missing
            else "audio_models está desligado"
        )
        typer.echo(f"erro: sem modelos nesta máquina ({why})", err=True)
        raise typer.Exit(1)
    with open_db(settings.db_path) as db:
        candidates = db.scalars(
            select(MediaFile).where(MediaFile.session_id == session).order_by(MediaFile.ordinal)
        )
        existing = [
            m for m in candidates if Path(m.path).is_file() and (file is None or file in Path(m.path).name)
        ]
        media = existing[0] if existing else None
        if media is None:
            typer.echo(f"erro: sessão {session} sem arquivos (veja `cronista status`)", err=True)
            raise typer.Exit(1)
        artifact = db.scalar(
            select(Artifact).where(
                Artifact.media_file_id == media.id, Artifact.stage == "audio", Artifact.variant == ""
            )
        )
        if artifact is None:
            typer.echo("erro: sem WAVs extraídos; rode `cronista ingest` antes", err=True)
            raise typer.Exit(1)
        wavs = StageResult.model_validate_json(Path(artifact.result_path).read_text(encoding="utf-8")).data
    work = settings.data_dir / "bench" / f"audio-{session}"
    rows = run_bench(models, Path(wavs[MIC_TRACK]), Path(wavs[GAME_TRACK]), work, minutes)
    typer.echo(render_table(rows))
    target = out or settings.data_dir / "bench" / f"audio-{session}.json"
    write_results(rows, target)
    typer.echo(f"\n{target}")


@app.command("bench-quality")
def bench_quality(
    session: Annotated[int, typer.Argument(help="Sessão analisada (`cronista analyze`)")],
    gabarito: Annotated[Path, typer.Argument(help="CSV do gabarito deste arquivo")],
    file: Annotated[str | None, typer.Option(help="Parte do nome do arquivo (padrão: o primeiro)")] = None,
    tolerance: Annotated[float, typer.Option(help="Tolerância de eventos, em segundos")] = 1.0,
) -> None:
    """Compara eventos e transcrição do banco com o gabarito (WER, risada, grito, teclado, farm)."""
    from cronista.audio.events import load_stored_events
    from cronista.audio.quality import Utterance, evaluate, render

    settings = load_settings()
    setup_logging(settings.log_level)
    report = validate_gabarito(gabarito)
    if not report.ok:
        for err in report.errors:
            typer.echo(f"erro: {err}", err=True)
        raise typer.Exit(1)
    with open_db(settings.db_path) as db:
        media = [
            m
            for m in db.scalars(
                select(MediaFile).where(MediaFile.session_id == session).order_by(MediaFile.ordinal)
            )
            if file is None or file in Path(m.path).name
        ]
        if not media:
            typer.echo(f"erro: sessão {session} sem arquivos (veja `cronista status`)", err=True)
            raise typer.Exit(1)
        # Métricas do microfone: eventos da faixa do jogo (música, explosão) não entram na conta.
        events = [
            s.event
            for s in load_stored_events(db, media[0].id)
            if s.event.kind == "fala" or s.variant.startswith("mic")
        ]
    if not events:
        typer.echo("erro: sem eventos no banco; rode `cronista analyze` antes", err=True)
        raise typer.Exit(1)
    utterances = [
        Utterance(e.evidence.start_frame, e.evidence.end_frame, e.evidence.quote or "")
        for e in events
        if e.kind == "fala"
    ]
    marks = [(e.kind, (e.evidence.start_frame, e.evidence.end_frame)) for e in events if e.kind != "fala"]
    routines = [iv for kind, iv in marks if kind == "rotina"]
    total = max([a.end_frame for a in report.annotations] + [iv[1] for _, iv in marks], default=0)
    typer.echo(render(evaluate(report.annotations, utterances, marks, routines, total, tolerance)))
    if not routines:
        typer.echo("aviso: a análise ainda não grava eventos `rotina`; revocação de farm não é confiável")


@app.command("gabarito-ui")
def gabarito_ui(
    session: Annotated[int, typer.Argument(help="Sessão analisada")],
    file: Annotated[str | None, typer.Option(help="Parte do nome do arquivo (padrão: o primeiro)")] = None,
    out: Annotated[Path | None, typer.Option(help="HTML de saída")] = None,
) -> None:
    """Gera uma página para anotar o gabarito vendo o vídeo, com sugestões da análise já preenchidas."""
    from cronista.audio.annotate_ui import build_suggestions, render_annotator
    from cronista.audio.events import load_events

    settings = load_settings()
    setup_logging(settings.log_level)
    with open_db(settings.db_path) as db:
        media = [
            m
            for m in db.scalars(
                select(MediaFile).where(MediaFile.session_id == session).order_by(MediaFile.ordinal)
            )
            if file is None or file in Path(m.path).name
        ]
        if not media:
            typer.echo(f"erro: sessão {session} sem arquivos (veja `cronista status`)", err=True)
            raise typer.Exit(1)
        item = media[0]
        proxy = db.scalar(
            select(Artifact).where(
                Artifact.media_file_id == item.id, Artifact.stage == "proxy", Artifact.variant == ""
            )
        )
        if proxy is None:
            typer.echo("erro: sem proxy; rode `cronista ingest` antes", err=True)
            raise typer.Exit(1)
        result = StageResult.model_validate_json(Path(proxy.result_path).read_text(encoding="utf-8"))
        proxy_path = Path(result.data["proxy"])
        events = [
            (e.kind, e.evidence.start_frame, e.evidence.end_frame, e.evidence.confidence, e.evidence.quote)
            for e in load_events(db, item.id)
        ]
    page = render_annotator(proxy_path, build_suggestions(events), Path(item.path).name)
    target = out or settings.data_dir / "gabarito" / f"anotar-{session}.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding="utf-8")
    typer.echo(f"{target}\n{len(events)} eventos viraram sugestões; abra o arquivo no navegador.")

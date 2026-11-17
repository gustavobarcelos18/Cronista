"""CLI: `cronista ingest <pasta>`, `status`, `preview <sessão>`, `export <sessão>`, `fixtures`."""

from __future__ import annotations

import asyncio
import json
import sys
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session

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
from cronista.pipeline import StageError, recover_orphans
from cronista.preview import PreviewError, build_preview
from cronista.profiles import build_models_with_profile
from cronista.recorder.feedback import ConsoleFeedback
from cronista.recorder.hotkeys import HotkeyConfigError
from cronista.recorder.run import run_forever
from cronista.video.models import build_video_models
from cronista.watch import Processed
from cronista.watch import serve as watch_serve


class AnalysisPart(StrEnum):
    AUDIO = "audio"
    VIDEO = "video"


def _pick_media(db: Session, session: int, file: str | None) -> MediaFile:
    """Primeiro arquivo da sessão (ou o primeiro cujo nome contém `file`); sai com erro se não houver."""
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
    return media[0]


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
    only: Annotated[AnalysisPart | None, typer.Option(help="`audio` ou `video` (padrão: os dois)")] = None,
) -> None:
    """Análise da sessão: áudio (sinais, fala, eventos) e vídeo (cenas, menu, loading, idle, câmera)."""
    settings = load_settings()
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
            try:
                run_ffmpeg(
                    settings,
                    ["-ss", f"{frame_to_seconds(a.start_frame):.3f}",
                     "-t", f"{frame_to_seconds(a.end_frame - a.start_frame):.3f}", "-i", str(video),
                     "-map", "0:v:0", "-map", "0:a:0", "-vf", "scale=640:-2,fps=30,format=yuv420p",
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-c:a", "aac", str(out)],
                )  # fmt: skip
            except StageError as exc:
                typer.echo(f"erro: prévia da linha {a.line}: {exc}", err=True)
                raise typer.Exit(1) from exc
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


@app.command("bench-video")
def bench_video(
    session: Annotated[int, typer.Argument(help="Sessão cujo primeiro arquivo serve de amostra")],
    models: Annotated[
        str,
        typer.Option(help="Candidatos separados por vírgula (veja CANDIDATES em video/models.py)"),
    ] = "siglip-base,siglip2-base,siglip2-so400m,clip-b32",
    truth: Annotated[
        Path | None, typer.Option(help="CSV inicio_s,fim_s,rotulo para medir qualidade (opcional)")
    ] = None,
    file: Annotated[
        str | None, typer.Option(help="Parte do nome do arquivo (padrão: o primeiro que existe)")
    ] = None,
    out: Annotated[Path | None, typer.Option(help="JSON de saída (padrão: data/bench/video-N.json)")] = None,
) -> None:
    """Benchmark dos modelos de embedding de quadro: velocidade, VRAM e acerto no gabarito pequeno."""
    from cronista.audio.models import missing_ml_packages
    from cronista.video.bench import load_truth, render_table, run_bench, write_results
    from cronista.video.models import CANDIDATES, make_candidate

    settings = load_settings()
    setup_logging(settings.log_level)
    names = [n.strip() for n in models.split(",") if n.strip()]
    unknown = [n for n in names if n not in CANDIDATES]
    if unknown or missing_ml_packages():
        typer.echo(
            f"erro: candidatos desconhecidos {unknown} ou faltam pacotes {missing_ml_packages()}", err=True
        )
        raise typer.Exit(1)
    with open_db(settings.db_path) as db:
        candidates = db.scalars(
            select(MediaFile).where(MediaFile.session_id == session).order_by(MediaFile.ordinal)
        )
        existing = [
            m for m in candidates if Path(m.path).is_file() and (file is None or file in Path(m.path).name)
        ]
        if not existing:
            typer.echo(f"erro: sessão {session} sem arquivos (veja `cronista status`)", err=True)
            raise typer.Exit(1)
        artifact = db.scalar(
            select(Artifact).where(
                Artifact.media_file_id == existing[0].id, Artifact.stage == "proxy", Artifact.variant == ""
            )
        )
        if artifact is None:
            typer.echo("erro: sem proxy; rode `cronista ingest` antes", err=True)
            raise typer.Exit(1)
        proxy = Path(
            str(
                StageResult.model_validate_json(Path(artifact.result_path).read_text(encoding="utf-8")).data[
                    "proxy"
                ]
            )
        )
    factories = {n: (lambda n=n: make_candidate(settings, n)) for n in names}
    target = out or settings.data_dir / "bench" / f"video-{session}.json"
    rows = run_bench(
        settings,
        proxy,
        factories,
        load_truth(truth) if truth else None,
        save_dir=settings.data_dir / "bench" / f"video-{session}",
        progress=lambda partial: write_results(partial, target),
    )
    typer.echo(render_table(rows))
    write_results(rows, target)
    typer.echo(f"\n{target}")


@app.command("bench-audio-quality")
def bench_audio_quality(
    session: Annotated[int, typer.Argument(help="Sessão com o gabarito")],
    gabarito: Annotated[Path, typer.Argument(help="CSV do gabarito deste arquivo")],
    speech: Annotated[str, typer.Option(help="Candidatos de fala, separados por vírgula (ou vazio)")] = "",
    events: Annotated[str, typer.Option(help="Candidatos de eventos no microfone (ou vazio)")] = "",
    file: Annotated[str | None, typer.Option(help="Parte do nome do arquivo (padrão: o primeiro)")] = None,
    out: Annotated[
        Path | None, typer.Option(help="JSON de saída (padrão: data/bench/audio-quality-N.json)")
    ] = None,
) -> None:
    """Compara fala e eventos sonoros com o gabarito: WER, precisão, revocação, tempo e VRAM."""
    from cronista.audio.bench_quality import AudioQualityRow, render_table, run_quality_bench, to_json
    from cronista.audio.models import (
        EVENT_CANDIDATES,
        SPEECH_CANDIDATES,
        make_event_candidate,
        make_speech_candidate,
        missing_ml_packages,
    )

    settings = load_settings()
    setup_logging(settings.log_level)
    speech_names = [n.strip() for n in speech.split(",") if n.strip()]
    event_names = [n.strip() for n in events.split(",") if n.strip()]
    unknown = [n for n in speech_names if n not in SPEECH_CANDIDATES] + [
        n for n in event_names if n not in EVENT_CANDIDATES
    ]
    if unknown or missing_ml_packages():
        typer.echo(
            f"erro: candidatos desconhecidos {unknown} ou faltam pacotes {missing_ml_packages()}", err=True
        )
        raise typer.Exit(1)
    report = validate_gabarito(gabarito)
    if not report.ok:
        for err in report.errors:
            typer.echo(f"erro: {err}", err=True)
        raise typer.Exit(1)
    with open_db(settings.db_path) as db:
        item = _pick_media(db, session, file)
        artifact = db.scalar(
            select(Artifact).where(
                Artifact.media_file_id == item.id, Artifact.stage == "audio", Artifact.variant == ""
            )
        )
        if artifact is None:
            typer.echo("erro: sem WAVs extraídos; rode `cronista ingest` antes", err=True)
            raise typer.Exit(1)
        wavs = StageResult.model_validate_json(Path(artifact.result_path).read_text(encoding="utf-8")).data
    target = out or settings.data_dir / "bench" / f"audio-quality-{session}.json"

    def save(partial_rows: list[AudioQualityRow]) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(to_json(partial_rows), indent=2, ensure_ascii=False), encoding="utf-8")

    rows = run_quality_bench(
        settings,
        wavs,
        report.annotations,
        {n: partial(make_speech_candidate, settings, n) for n in speech_names},
        {n: partial(make_event_candidate, settings, n) for n in event_names},
        settings.data_dir / "bench" / f"audio-quality-{session}",
        progress=save,
    )
    typer.echo(render_table(rows))
    typer.echo(f"\n{target}")


@app.command("bench-vision")
def bench_vision(
    session: Annotated[int, typer.Argument(help="Sessão cujo primeiro arquivo serve de amostra")],
    truth: Annotated[Path, typer.Argument(help="JSON do gabarito visual (telas e texto do HUD)")],
    vlms: Annotated[str, typer.Option(help="VLMs separados por vírgula (ou vazio)")] = (
        "qwen25vl-3b,qwen25vl-7b-4bit,qwen3vl-4b,qwen3vl-8b-4bit"
    ),
    ocr: Annotated[bool, typer.Option(help="Inclui o RapidOCR")] = True,
    file: Annotated[str | None, typer.Option(help="Parte do nome do arquivo (padrão: o primeiro)")] = None,
    out: Annotated[Path | None, typer.Option(help="JSON de saída (padrão: data/bench/vision-N.json)")] = None,
) -> None:
    """Estado de tela por VLM, leitura de HUD (OCR e VLM) e efeito da resolução (360p, 720p e 1080p)."""
    from cronista.video.bench_vision import (
        VLM_CANDIDATES,
        load_truth,
        render_table,
        run_vision_bench,
    )

    settings = load_settings()
    setup_logging(settings.log_level)
    names = [n.strip() for n in vlms.split(",") if n.strip()]
    unknown = [n for n in names if n not in VLM_CANDIDATES]
    if unknown:
        typer.echo(f"erro: VLMs desconhecidos {unknown}", err=True)
        raise typer.Exit(1)
    with open_db(settings.db_path) as db:
        item = _pick_media(db, session, file)
        artifact = db.scalar(
            select(Artifact).where(
                Artifact.media_file_id == item.id, Artifact.stage == "proxy", Artifact.variant == ""
            )
        )
        if artifact is None:
            typer.echo("erro: sem proxy; rode `cronista ingest` antes", err=True)
            raise typer.Exit(1)
        data = StageResult.model_validate_json(Path(artifact.result_path).read_text(encoding="utf-8")).data
        proxy, master = Path(str(data["proxy"])), Path(item.path)
    target = out or settings.data_dir / "bench" / f"vision-{session}.json"
    rows = run_vision_bench(
        settings,
        master,
        proxy,
        load_truth(truth),
        names,
        ocr,
        settings.data_dir / "bench" / "vision-frames",
        target,
    )
    typer.echo(render_table(rows))
    typer.echo(f"\n{target}")


@app.command("bench-report")
def bench_report(
    out: Annotated[Path, typer.Option(help="Pasta dos relatórios")] = Path("docs/benchmarks"),
) -> None:
    """Gera os relatórios Markdown dos benchmarks (tabelas automáticas; a análise à mão é preservada)."""
    from cronista.bench_report import write_reports

    settings = load_settings()
    for path in write_reports(settings.data_dir / "bench", out):
        typer.echo(str(path))


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
        item = _pick_media(db, session, file)
        # Métricas do microfone: eventos da faixa do jogo (música, explosão) não entram na conta.
        events = [
            s.event
            for s in load_stored_events(db, item.id)
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


@app.command("relevance")
def relevance(
    session: Annotated[int, typer.Argument(help="Sessão analisada (`cronista analyze`)")],
    top: Annotated[int, typer.Option(help="Quantos candidatos mostrar por arquivo")] = 15,
) -> None:
    """Segmenta a sessão, dá nota explicável a cada trecho e grava os segmentos (Fase 4)."""
    from cronista.relevance.quality import top_candidates
    from cronista.relevance.service import RelevanceError, relevance_session

    settings = load_settings()
    setup_logging(settings.log_level)
    with open_db(settings.db_path) as db:
        try:
            results = relevance_session(db, session)
        except RelevanceError as exc:
            typer.echo(f"erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    for res in results:
        counts: dict[str, int] = {}
        for s in res.segments:
            counts[s.classe] = counts.get(s.classe, 0) + 1
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        typer.echo(f"{res.name}: {len(res.segments)} segmentos ({summary})")
        for s in sorted(top_candidates(res.segments, top), key=lambda x: -x.score):
            a, b = int(s.start_s), int(s.end_s)
            typer.echo(
                f"  {a // 60}:{a % 60:02d}-{b // 60}:{b % 60:02d} {s.classe:<10} nota {s.score:.2f}  "
                + "; ".join(s.razoes)
            )


@app.command("bench-relevance")
def bench_relevance(
    session: Annotated[int, typer.Argument(help="Sessão com segmentos (`cronista relevance`)")],
    gabarito: Annotated[Path, typer.Argument(help="CSV do gabarito deste arquivo")],
    file: Annotated[str | None, typer.Option(help="Parte do nome do arquivo (padrão: o primeiro)")] = None,
    top: Annotated[int, typer.Option(help="Tamanho do topo de candidatos")] = 30,
) -> None:
    """Momentos do gabarito no topo, farm como farm e compressão (meta: 85% dos momentos no topo)."""
    from cronista.relevance.quality import evaluate_relevance, render_quality
    from cronista.relevance.service import load_segments

    settings = load_settings()
    setup_logging(settings.log_level)
    report = validate_gabarito(gabarito)
    if not report.ok:
        for err in report.errors:
            typer.echo(f"erro: {err}", err=True)
        raise typer.Exit(1)
    with open_db(settings.db_path) as db:
        item = _pick_media(db, session, file)
        segments = load_segments(db, item.id)
    if not segments:
        typer.echo("erro: sem segmentos no banco; rode `cronista relevance` antes", err=True)
        raise typer.Exit(1)
    typer.echo(render_quality(evaluate_relevance(report.annotations, segments, top)))


@app.command("series")
def series() -> None:
    """Painel da série: horas gravadas e minutos estimados de produto por sessão, e o acumulado."""
    from cronista.relevance.service import series_panel

    settings = load_settings()
    with open_db(settings.db_path) as db:
        rows = series_panel(db)
    typer.echo(f"{'sessão':>7}{'gravado (h)':>13}{'produto (min)':>15}{'acumulado (min)':>17}")
    for r in rows:
        typer.echo(f"{r['sessao']:>7}{r['gravado_h']:>13}{r['produto_min']:>15}{r['acumulado_min']:>17}")
    typer.echo(
        "estimativa: trechos relevantes (até 45 s cada) + farm em timelapse; alvo do vídeo: 30 a 50 min"
    )


@app.command("story")
def story(
    session: Annotated[int, typer.Argument(help="Sessão com segmentos (`cronista relevance`)")],
    target_min: Annotated[float, typer.Option(help="Duração-alvo do vídeo, em minutos")] = 40.0,
    out: Annotated[Path | None, typer.Option(help="Pasta de saída (padrão: data/story/<sessão>)")] = None,
) -> None:
    """Capítulos, beats, objetivos e `story-pack.json` para o roteiro (Fases 5 e 5A)."""
    from cronista.profiles import load_settings_profile
    from cronista.story.service import StoryError, build_story, write_pack

    settings = load_settings()
    setup_logging(settings.log_level)
    try:
        profile = load_settings_profile(settings)
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"erro: {exc}", err=True)
        raise typer.Exit(1) from exc
    with open_db(settings.db_path) as db:
        try:
            result = build_story(db, session, target_min * 60, (profile.objetivos, profile.regras))
        except StoryError as exc:
            typer.echo(f"erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    target = out or settings.data_dir / "story" / str(session)
    pack_path, voice_path = write_pack(target, result)
    for c in result.chapters:
        beats = ", ".join(f"{i.beat.value}" for i in c.items[:8])
        typer.echo(f"capítulo {c.number}: {len(c.items)} trechos, {c.allocated_s:.0f} s alocados ({beats})")
    d = result.discovery
    typer.echo(
        f"objetivos: {d.confirmed} confirmados, {d.hypotheses} hipóteses, {d.rejected} citações rejeitadas"
    )
    typer.echo(f"{pack_path}\n{voice_path}\nAgora rode /roteirizar no Claude Code com este pacote.")


@app.command("revisao")
def revisao(
    project: Annotated[int, typer.Argument(help="Projeto (veja `cronista status`)")] = 1,
    out: Annotated[Path | None, typer.Option(help="CSV de saída")] = None,
) -> None:
    """Fila de revisão: objetivos propostos ou incertos (nunca afirmados nem descartados)."""
    from cronista.story.objectives import export_review_csv, review_queue

    settings = load_settings()
    with open_db(settings.db_path) as db:
        items = review_queue(db, project)
        target = export_review_csv(items, out or settings.data_dir / "story" / f"revisao-{project}.csv")
    typer.echo(f"{len(items)} itens para revisar: {target}")


@app.command("roteiro-import")
def roteiro_import(
    session: Annotated[int, typer.Argument(help="Sessão do story-pack usado")],
    script: Annotated[Path, typer.Argument(help="roteiro.json escrito pelo /roteirizar")],
) -> None:
    """Valida o roteiro (segmento, espaço livre, antecipação justificada, sinais de IA) e gera o SRT."""
    from cronista.story.script import load_script, to_srt, validate_script
    from cronista.story.service import segment_index

    settings = load_settings()
    folder = settings.data_dir / "story" / str(session)
    pack_path = folder / "story-pack.json"
    if not pack_path.is_file():
        typer.echo("erro: rode `cronista story` antes", err=True)
        raise typer.Exit(1)
    try:
        loaded = load_script(script)
    except ValueError as exc:
        typer.echo(f"erro: {exc}", err=True)
        raise typer.Exit(1) from exc
    index = segment_index(json.loads(pack_path.read_text(encoding="utf-8")))
    report = validate_script(loaded, index)
    for err in report.errors:
        typer.echo(f"erro: {err}", err=True)
    for warn in report.warnings:
        typer.echo(f"aviso: {warn}")
    if not report.ok:
        raise typer.Exit(1)
    starts = {sid: gaps[0][0] if gaps else a for sid, (a, _b, gaps) in index.items()}
    loaded = loaded.model_copy(update={"lines": report.lines})
    (folder / "roteiro.json").write_text(loaded.model_dump_json(indent=1), encoding="utf-8")
    (folder / "roteiro.srt").write_text(to_srt(report.lines, starts), encoding="utf-8")
    total = sum(line.est_s or 0 for line in report.lines)
    typer.echo(f"{len(report.lines)} falas, ~{total:.0f} s de narração; {folder / 'roteiro.srt'}")


@app.command("roteiro-lint")
def roteiro_lint(text: Annotated[Path, typer.Argument(help="Arquivo de texto ou roteiro.json")]) -> None:
    """Aponta sinais de texto de IA (padrões do /humanizar) numa narração."""
    from cronista.story.script import lint_text

    raw = text.read_text(encoding="utf-8-sig")
    pieces = (
        [line["text"] for line in json.loads(raw)["lines"]] if text.suffix == ".json" else raw.splitlines()
    )
    found = 0
    for n, piece in enumerate(pieces, start=1):
        flags = lint_text(piece)
        if flags:
            found += 1
            typer.echo(f"{n}: {', '.join(flags)} | {piece[:80]}")
    typer.echo(f"{found} de {len(pieces)} falas com sinais de IA")


@app.command("bench-video-quality")
def bench_video_quality(
    session: Annotated[int, typer.Argument(help="Sessão analisada (`cronista analyze`)")],
    gabarito: Annotated[Path, typer.Argument(help="CSV do gabarito deste arquivo")],
    file: Annotated[str | None, typer.Option(help="Parte do nome do arquivo (padrão: o primeiro)")] = None,
    tolerance: Annotated[float, typer.Option(help="Tolerância das bordas, em segundos")] = 2.0,
) -> None:
    """Compara menu, loading, idle e HUD oculto do banco com o gabarito (precisão, revocação, bordas)."""
    from cronista.audio.events import load_stored_events
    from cronista.video.quality import VIDEO_CLASSES, evaluate_video, render_video_quality
    from cronista.video.report import is_video_event

    settings = load_settings()
    setup_logging(settings.log_level)
    report = validate_gabarito(gabarito)
    if not report.ok:
        for err in report.errors:
            typer.echo(f"erro: {err}", err=True)
        raise typer.Exit(1)
    with open_db(settings.db_path) as db:
        item = _pick_media(db, session, file)
        stored = [s for s in load_stored_events(db, item.id) if is_video_event(s)]
    if not stored:
        typer.echo("erro: sem eventos de vídeo no banco; rode `cronista analyze` antes", err=True)
        raise typer.Exit(1)
    predicted: dict[str, list[tuple[int, int]]] = {}
    for s in stored:
        if s.event.kind in VIDEO_CLASSES:
            ev = s.event.evidence
            predicted.setdefault(s.event.kind, []).append((ev.start_frame, ev.end_frame))
    total = max(
        [a.end_frame for a in report.annotations] + [iv[1] for ivs in predicted.values() for iv in ivs],
        default=0,
    )
    typer.echo(
        render_video_quality(evaluate_video(report.annotations, predicted, total, tolerance), tolerance)
    )
    typer.echo(
        "aviso: 'falsos/30min' só vale se o gabarito cobre a sessão toda; "
        "previstos fora dos trechos anotados contam como falsos"
    )


@app.command("gabarito-ui")
def gabarito_ui(
    session: Annotated[int, typer.Argument(help="Sessão analisada")],
    file: Annotated[str | None, typer.Option(help="Parte do nome do arquivo (padrão: o primeiro)")] = None,
    out: Annotated[Path | None, typer.Option(help="HTML de saída")] = None,
    visual: Annotated[
        bool,
        typer.Option("--visual", help="Candidatos visuais (menu, loading, idle, HUD oculto) com miniatura"),
    ] = False,
) -> None:
    """Gera uma página para anotar o gabarito vendo o vídeo, com sugestões da análise já preenchidas."""
    from cronista.audio.annotate_ui import VISUAL_CLASSES_UI, build_suggestions, render_annotator
    from cronista.audio.events import load_stored_events
    from cronista.video.report import is_video_event, thumbnail

    settings = load_settings()
    setup_logging(settings.log_level)
    with open_db(settings.db_path) as db:
        item = _pick_media(db, session, file)
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
            for s in load_stored_events(db, item.id)
            if is_video_event(s) == visual  # sem `--visual` o anotador é de áudio; com, só os estados de tela
            for e in [s.event]
        ]
    if visual:
        suggestions = build_suggestions(
            events, VISUAL_CLASSES_UI, lambda frame: thumbnail(settings, proxy_path, frame)
        )
    else:
        suggestions = build_suggestions(events)
    page = render_annotator(proxy_path, suggestions, Path(item.path).name, "visual" if visual else "audio")
    target = out or settings.data_dir / "gabarito" / f"anotar-{session}.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding="utf-8")
    typer.echo(f"{target}\n{len(suggestions)} sugestões; abra o arquivo no navegador.")


@app.command("broll-search")
def broll_search(
    session: Annotated[int, typer.Argument(help="Número da sessão (veja `cronista status`)")],
    query: Annotated[str, typer.Argument(help='Texto em inglês, ex.: "a cave" ou "a sunset over the lake"')],
    top: Annotated[int, typer.Option(help="Quantos resultados mostrar")] = 5,
    file: Annotated[str | None, typer.Option(help="Parte do nome do arquivo (padrão: o primeiro)")] = None,
) -> None:
    """Busca B-roll da sessão por texto (precisa de `analyze` com `video_embedder` na configuração)."""
    import numpy as np

    from cronista.audio.events import load_stored_events
    from cronista.video import broll as broll_lib

    settings = load_settings()
    models = build_video_models(settings)
    if models.embedder is None:
        typer.echo("erro: sem `video_embedder` na configuração (ou sem o grupo `ml`)", err=True)
        raise typer.Exit(1)
    with open_db(settings.db_path) as db:
        media = _pick_media(db, session, file)
        art = db.scalar(
            select(Artifact)
            .where(Artifact.media_file_id == media.id, Artifact.stage == "video_embeddings")
            .order_by(Artifact.id.desc())
        )
        stored = load_stored_events(db, media.id, kind="broll")
    if art is None or not stored:
        typer.echo("erro: sem B-roll nem embeddings; rode `cronista analyze` antes", err=True)
        raise typer.Exit(1)
    info = StageResult.model_validate_json(Path(art.result_path).read_text(encoding="utf-8"))
    saved = info.data["embeddings"]
    current = [models.embedder.name, models.embedder.version, models.embedder.options]
    if saved["dim"] != models.embedder.dim or saved.get("embedder", current) != current:
        typer.echo(
            "erro: os embeddings da sessão vieram de outro modelo (`video_embedder` mudou); "
            "rode `cronista analyze` de novo",
            err=True,
        )
        raise typer.Exit(1)
    emb = np.load(saved["path"], mmap_mode="r")
    hits = broll_lib.search(
        np.asarray(emb, dtype=np.float32),
        models.embedder,
        [s.event for s in stored],
        query,
        hop=60,
        top=top,
    )
    for ev, score in hits:
        a, b = ev.evidence.start_frame, ev.evidence.end_frame
        tags = ", ".join(str(t) for t in ev.payload.get("tags", []))
        typer.echo(
            f"{frame_to_seconds(a):7.1f} s  +{(b - a) // 60:>3} s  sim={score:.3f}  "
            f"util={ev.evidence.confidence:.2f}  {tags}"
        )


@app.command("montar")
def montar(
    session: Annotated[int, typer.Argument(help="Sessão com segmentos (`cronista relevance`)")],
    target_min: Annotated[float, typer.Option(help="Duração-alvo do vídeo, em minutos")] = 40.0,
    out: Annotated[Path | None, typer.Option(help="Pasta de saída (padrão: data/montagem/<sessão>)")] = None,
) -> None:
    """Plano de montagem em quadros a 60 fps: cortes, timelapses, B-roll e cartelas (Fase 6A)."""
    from cronista.assembly.service import build_assembly, write_plan
    from cronista.profiles import load_settings_profile
    from cronista.story.service import StoryError

    settings = load_settings()
    setup_logging(settings.log_level)
    try:
        profile = load_settings_profile(settings)
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"erro: {exc}", err=True)
        raise typer.Exit(1) from exc
    with open_db(settings.db_path) as db:
        try:
            plan = build_assembly(db, session, settings, target_min * 60, (profile.objetivos, profile.regras))
        except StoryError as exc:
            typer.echo(f"erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    path = write_plan(plan, out or settings.data_dir / "montagem" / str(session), session)
    for number, budget in plan.chapter_budget_s.items():
        typer.echo(f"capítulo {number}: {plan.chapter_s(number):.0f} s de {budget:.0f} s alocados")
    typer.echo(
        f"total: {plan.total_s / 60:.1f} min em {len(plan.v1)} cortes"
        f" ({len(plan.items) - len(plan.v1)} B-roll)"
    )
    for warning in plan.warnings:
        typer.echo(f"aviso: {warning}")
    typer.echo(str(path))


@app.command("mixar")
def mixar(
    session: Annotated[int, typer.Argument(help="Sessão com segmentos (`cronista relevance`)")],
    script: Annotated[
        Path | None, typer.Option(help="roteiro.json validado (ducking sob a narração)")
    ] = None,
    target_min: Annotated[float, typer.Option(help="Duração-alvo do vídeo, em minutos")] = 40.0,
    out: Annotated[
        Path | None, typer.Option(help="Pasta dos stems (padrão: data/export/stems/<sessão>)")
    ] = None,
) -> None:
    """Stems A1/A2 nivelados (ducking, cadeia de voz) e crus A6/A7, só dos trechos usados (Fase 6B)."""
    from cronista.mix.service import mix_session
    from cronista.montage import SessionPlanError
    from cronista.pipeline.stage import StageError
    from cronista.profiles import load_settings_profile
    from cronista.story.script import load_script
    from cronista.story.service import StoryError

    settings = load_settings()
    setup_logging(settings.log_level)
    try:
        profile = load_settings_profile(settings)
        loaded = load_script(script) if script else None
        with open_db(settings.db_path) as db:
            report = mix_session(
                db,
                session,
                settings,
                loaded,
                target_min * 60,
                (profile.objetivos, profile.regras),
                out,
            )
    except (FileNotFoundError, ValueError, StoryError, SessionPlanError, StageError) as exc:
        typer.echo(f"erro: {exc}", err=True)
        raise typer.Exit(1) from exc
    for stem in report.stems:
        lufs = "silêncio" if stem.lufs is None else f"{stem.lufs:.1f} LUFS"
        peak = "-" if stem.true_peak_db is None else f"{stem.true_peak_db:.1f} dBFS"
        typer.echo(f"{stem.name}: {lufs}, pico {peak}, ganho {stem.gain_db:+.1f} dB")
    typer.echo(f"ducking em {report.ducked_s:.0f} s")
    for warning in report.warnings:
        typer.echo(f"aviso: {warning}")
    typer.echo(str(report.directory))


@app.command("montagem")
def montagem(
    session: Annotated[int, typer.Argument(help="Sessão com segmentos (`cronista relevance`)")],
    script: Annotated[Path | None, typer.Option(help="roteiro.json validado")] = None,
    target_min: Annotated[float, typer.Option(help="Duração-alvo do vídeo, em minutos")] = 40.0,
    out: Annotated[
        Path | None, typer.Option(help="Base da exportação (padrão: data/export/montagem/<sessão>)")
    ] = None,
) -> None:
    """Pacote para o Resolve: FCPXML multi-trilha, stems, SRT, marcadores em Lua e manifesto (Fase 6C)."""
    from cronista.export.pacote import export_montagem
    from cronista.montage import SessionPlanError
    from cronista.pipeline.stage import StageError
    from cronista.profiles import load_settings_profile
    from cronista.story.script import load_script
    from cronista.story.service import StoryError

    settings = load_settings()
    setup_logging(settings.log_level)
    try:
        profile = load_settings_profile(settings)
        loaded = load_script(script) if script else None
        with open_db(settings.db_path) as db:
            report = export_montagem(
                db,
                session,
                settings,
                loaded,
                target_min * 60,
                (profile.objetivos, profile.regras),
                out,
                build_gate(settings),
            )
    except (FileNotFoundError, ValueError, StoryError, SessionPlanError, StageError) as exc:
        typer.echo(f"erro: {exc}", err=True)
        raise typer.Exit(1) from exc
    if report.reused:
        typer.echo("nada mudou desde a última versão completa: reaproveitada, nada foi regerado")
    typer.echo(
        f"versão {report.version}: {report.duration_s / 60:.1f} min, {report.clips} cortes,"
        f" {report.markers} marcadores"
    )
    for problem in report.problems:
        typer.echo(f"problema: {problem}", err=True)
    for warning in report.warnings:
        typer.echo(f"aviso: {warning}")
    typer.echo(f"{report.directory}\nLeia o LEIA-ME.md da pasta para importar no Resolve.")
    if report.problems:
        raise typer.Exit(2)


@app.command("shorts")
def shorts(
    session: Annotated[int, typer.Argument(help="Sessão com segmentos (`cronista relevance`)")],
    top: Annotated[int, typer.Option(help="Quantos candidatos listar")] = 10,
    out: Annotated[Path | None, typer.Option(help="Pasta de saída (padrão: data/shorts/<sessão>)")] = None,
) -> None:
    """Candidatos a Shorts: até 13 s, gancho nos 3 primeiros segundos (Fase 6D; a finalização é da Fase 9)."""
    from cronista.shorts.candidates import ShortsParams
    from cronista.shorts.service import build_shorts, write_shorts
    from cronista.story.service import StoryError

    settings = load_settings()
    setup_logging(settings.log_level)
    with open_db(settings.db_path) as db:
        try:
            found = build_shorts(db, session, ShortsParams(max_candidates=top))
        except StoryError as exc:
            typer.echo(f"erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    path = write_shorts(found, out or settings.data_dir / "shorts" / str(session), session)
    for n, c in enumerate(found, start=1):
        typer.echo(
            f"{n}. arquivo {c.file_id} {c.start_frame / 60:.1f}s: {c.duration_s:.1f} s, nota {c.score:.2f}, "
            f"gancho ({c.hook_kind}) em {c.hook_offset_s:.1f} s; {c.reason}"
        )
    if not found:
        typer.echo(
            "nenhum candidato: faltam momentos com pico (marcador ou emoção) e gancho nos 3 s iniciais"
        )
    typer.echo(str(path))


@app.command("api")
def api_cmd(
    port: Annotated[int, typer.Option(help="Porta da API local")] = 8000,
) -> None:
    """Sobe a API local que o Studio consome (Fase 7)."""
    import uvicorn

    from cronista.api.app import create_app

    uvicorn.run(create_app(load_settings()), host="127.0.0.1", port=port)

"""Ferramentas de desenvolvimento, benchmarks, gabarito e a API local."""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import select

from cronista.audio.models import build_models
from cronista.commands.common import (
    _pick_media,
    current_settings,
    profile_objectives,
)
from cronista.db.models import Artifact, MediaFile
from cronista.db.session import open_db
from cronista.devtools.fixtures import make_fixtures
from cronista.devtools.resolve_kit import make_resolve_kit
from cronista.domain.frames import frame_to_seconds
from cronista.domain.models import StageResult
from cronista.finishing.loader import default_loader
from cronista.gabarito import validate_gabarito
from cronista.ingest.ffmpeg import probe_media
from cronista.logging_setup import setup_logging
from cronista.media.ffmpeg import run_ffmpeg
from cronista.pipeline import StageError


def register(app: typer.Typer) -> None:
    @app.command()
    def gabarito(
        csv_path: Annotated[Path, typer.Argument(help="CSV com inicio,fim,classe,nota")],
        video: Annotated[
            Path | None, typer.Option(help="Vídeo anotado: confere a duração e serve à prévia")
        ] = None,
        previa: Annotated[
            Path | None,
            typer.Option(help="Pasta onde gravar um MP4 curto por anotação, para conferir de ouvido"),
        ] = None,
    ) -> None:
        """Valida o gabarito anotado à mão e resume o que há em cada classe (decisão D3)."""
        settings = current_settings()
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
        settings = current_settings()
        for name, path in make_resolve_kit(settings, out or settings.data_dir / "kit-resolve").items():
            typer.echo(f"{name}: {path}")

    @app.command()
    def fixtures(
        out: Annotated[Path | None, typer.Option(help="Pasta de saída (padrão: data/fixtures)")] = None,
    ) -> None:
        """Gera as fixtures sintéticas de vídeo (FFmpeg) para testar sem gravação real."""
        settings = current_settings()
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
        out: Annotated[
            Path | None, typer.Option(help="JSON de saída (padrão: data/bench/audio-N.json)")
        ] = None,
    ) -> None:
        """Benchmark de desempenho dos modelos de áudio (velocidade, VRAM, RAM). Qualidade é da Fase 2C."""
        from cronista.audio.bench import render_table, run_bench, write_results
        from cronista.audio.models import missing_ml_packages
        from cronista.audio.ports import GAME_TRACK, MIC_TRACK

        settings = current_settings()
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
                m
                for m in candidates
                if Path(m.path).is_file() and (file is None or file in Path(m.path).name)
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
            wavs = StageResult.model_validate_json(
                Path(artifact.result_path).read_text(encoding="utf-8")
            ).data
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
        out: Annotated[
            Path | None, typer.Option(help="JSON de saída (padrão: data/bench/video-N.json)")
        ] = None,
    ) -> None:
        """Benchmark dos modelos de embedding de quadro: velocidade, VRAM e acerto no gabarito pequeno."""
        from cronista.audio.models import missing_ml_packages
        from cronista.video.bench import load_truth, render_table, run_bench, write_results
        from cronista.video.models import CANDIDATES, make_candidate

        settings = current_settings()
        setup_logging(settings.log_level)
        names = [n.strip() for n in models.split(",") if n.strip()]
        unknown = [n for n in names if n not in CANDIDATES]
        if unknown or missing_ml_packages():
            typer.echo(
                f"erro: candidatos desconhecidos {unknown} ou faltam pacotes {missing_ml_packages()}",
                err=True,
            )
            raise typer.Exit(1)
        with open_db(settings.db_path) as db:
            candidates = db.scalars(
                select(MediaFile).where(MediaFile.session_id == session).order_by(MediaFile.ordinal)
            )
            existing = [
                m
                for m in candidates
                if Path(m.path).is_file() and (file is None or file in Path(m.path).name)
            ]
            if not existing:
                typer.echo(f"erro: sessão {session} sem arquivos (veja `cronista status`)", err=True)
                raise typer.Exit(1)
            artifact = db.scalar(
                select(Artifact).where(
                    Artifact.media_file_id == existing[0].id,
                    Artifact.stage == "proxy",
                    Artifact.variant == "",
                )
            )
            if artifact is None:
                typer.echo("erro: sem proxy; rode `cronista ingest` antes", err=True)
                raise typer.Exit(1)
            proxy = Path(
                str(
                    StageResult.model_validate_json(
                        Path(artifact.result_path).read_text(encoding="utf-8")
                    ).data["proxy"]
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
        speech: Annotated[
            str, typer.Option(help="Candidatos de fala, separados por vírgula (ou vazio)")
        ] = "",
        events: Annotated[str, typer.Option(help="Candidatos de eventos no microfone (ou vazio)")] = "",
        file: Annotated[
            str | None, typer.Option(help="Parte do nome do arquivo (padrão: o primeiro)")
        ] = None,
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

        settings = current_settings()
        setup_logging(settings.log_level)
        speech_names = [n.strip() for n in speech.split(",") if n.strip()]
        event_names = [n.strip() for n in events.split(",") if n.strip()]
        unknown = [n for n in speech_names if n not in SPEECH_CANDIDATES] + [
            n for n in event_names if n not in EVENT_CANDIDATES
        ]
        if unknown or missing_ml_packages():
            typer.echo(
                f"erro: candidatos desconhecidos {unknown} ou faltam pacotes {missing_ml_packages()}",
                err=True,
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
            wavs = StageResult.model_validate_json(
                Path(artifact.result_path).read_text(encoding="utf-8")
            ).data
        target = out or settings.data_dir / "bench" / f"audio-quality-{session}.json"

        def save(partial_rows: list[AudioQualityRow]) -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(to_json(partial_rows), indent=2, ensure_ascii=False), encoding="utf-8"
            )

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
        file: Annotated[
            str | None, typer.Option(help="Parte do nome do arquivo (padrão: o primeiro)")
        ] = None,
        out: Annotated[
            Path | None, typer.Option(help="JSON de saída (padrão: data/bench/vision-N.json)")
        ] = None,
    ) -> None:
        """Estado de tela por VLM, leitura de HUD (OCR e VLM) e efeito da resolução (360p, 720p e 1080p)."""
        from cronista.video.bench_vision import (
            VLM_CANDIDATES,
            load_truth,
            render_table,
            run_vision_bench,
        )

        settings = current_settings()
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
            data = StageResult.model_validate_json(
                Path(artifact.result_path).read_text(encoding="utf-8")
            ).data
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

        settings = current_settings()
        for path in write_reports(settings.data_dir / "bench", out):
            typer.echo(str(path))

    @app.command("bench-quality")
    def bench_quality(
        session: Annotated[int, typer.Argument(help="Sessão analisada (`cronista analyze`)")],
        gabarito: Annotated[Path, typer.Argument(help="CSV do gabarito deste arquivo")],
        file: Annotated[
            str | None, typer.Option(help="Parte do nome do arquivo (padrão: o primeiro)")
        ] = None,
        tolerance: Annotated[float, typer.Option(help="Tolerância de eventos, em segundos")] = 1.0,
    ) -> None:
        """Compara eventos e transcrição do banco com o gabarito (WER, risada, grito, teclado, farm)."""
        from cronista.audio.events import load_stored_events
        from cronista.audio.quality import Utterance, evaluate, render

        settings = current_settings()
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

    @app.command("bench-relevance")
    def bench_relevance(
        session: Annotated[int, typer.Argument(help="Sessão com segmentos (`cronista relevance`)")],
        gabarito: Annotated[Path, typer.Argument(help="CSV do gabarito deste arquivo")],
        file: Annotated[
            str | None, typer.Option(help="Parte do nome do arquivo (padrão: o primeiro)")
        ] = None,
        top: Annotated[int, typer.Option(help="Tamanho do topo de candidatos")] = 30,
    ) -> None:
        """Momentos do gabarito no topo, farm como farm e compressão (meta: 85% dos momentos no topo)."""
        from cronista.relevance.quality import evaluate_relevance, render_quality
        from cronista.relevance.service import load_segments

        settings = current_settings()
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

    @app.command("bench-video-quality")
    def bench_video_quality(
        session: Annotated[int, typer.Argument(help="Sessão analisada (`cronista analyze`)")],
        gabarito: Annotated[Path, typer.Argument(help="CSV do gabarito deste arquivo")],
        file: Annotated[
            str | None, typer.Option(help="Parte do nome do arquivo (padrão: o primeiro)")
        ] = None,
        tolerance: Annotated[float, typer.Option(help="Tolerância das bordas, em segundos")] = 2.0,
    ) -> None:
        """Compara menu, loading, idle e HUD oculto do banco com o gabarito (precisão, revocação, bordas)."""
        from cronista.audio.events import load_stored_events
        from cronista.video.quality import VIDEO_CLASSES, evaluate_video, render_video_quality
        from cronista.video.report import is_video_event

        settings = current_settings()
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
        file: Annotated[
            str | None, typer.Option(help="Parte do nome do arquivo (padrão: o primeiro)")
        ] = None,
        out: Annotated[Path | None, typer.Option(help="HTML de saída")] = None,
        visual: Annotated[
            bool,
            typer.Option(
                "--visual", help="Candidatos visuais (menu, loading, idle, HUD oculto) com miniatura"
            ),
        ] = False,
    ) -> None:
        """Gera uma página para anotar o gabarito vendo o vídeo, com sugestões da análise já preenchidas."""
        from cronista.audio.annotate_ui import VISUAL_CLASSES_UI, build_suggestions, render_annotator
        from cronista.audio.events import load_stored_events
        from cronista.video.report import is_video_event, thumbnail

        settings = current_settings()
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
                (
                    e.kind,
                    e.evidence.start_frame,
                    e.evidence.end_frame,
                    e.evidence.confidence,
                    e.evidence.quote,
                )
                for s in load_stored_events(db, item.id)
                if is_video_event(s)
                == visual  # sem `--visual` o anotador é de áudio; com, só os estados de tela
                for e in [s.event]
            ]
        if visual:
            suggestions = build_suggestions(
                events, VISUAL_CLASSES_UI, lambda frame: thumbnail(settings, proxy_path, frame)
            )
        else:
            suggestions = build_suggestions(events)
        page = render_annotator(
            proxy_path, suggestions, Path(item.path).name, "visual" if visual else "audio"
        )
        target = out or settings.data_dir / "gabarito" / f"anotar-{session}.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page, encoding="utf-8")
        typer.echo(f"{target}\n{len(suggestions)} sugestões; abra o arquivo no navegador.")

    @app.command("api")
    def api_cmd(
        port: Annotated[int, typer.Option(help="Porta da API local")] = 8000,
    ) -> None:
        """Sobe a API local que o Studio consome (Fase 7)."""
        import uvicorn

        from cronista.api.app import create_app

        settings = current_settings()

        uvicorn.run(
            create_app(
                settings,
                profile_loader=lambda: profile_objectives(settings),
                finishing_loader=default_loader(settings),
            ),
            host="127.0.0.1",
            port=port,
        )

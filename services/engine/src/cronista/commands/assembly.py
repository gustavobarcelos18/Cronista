"""Montagem, mixagem, acabamento e conferência do brand kit."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from cronista.commands.common import (
    current_settings,
    profile_objectives,
)
from cronista.db.session import open_db
from cronista.finishing.loader import load_style
from cronista.gates import build_gate
from cronista.logging_setup import setup_logging
from cronista.montage import SessionPlanError
from cronista.paths import SessionPaths, series_finishing_dir


def register(app: typer.Typer) -> None:
    @app.command("montar")
    def montar(
        session: Annotated[int, typer.Argument(help="Sessão com segmentos (`cronista relevance`)")],
        target_min: Annotated[float, typer.Option(help="Duração-alvo do vídeo, em minutos")] = 40.0,
        out: Annotated[
            Path | None, typer.Option(help="Pasta de saída (padrão: data/montagem/<sessão>)")
        ] = None,
    ) -> None:
        """Plano de montagem em quadros a 60 fps: cortes, timelapses, B-roll e cartelas (Fase 6A)."""
        from cronista.assembly.service import build_assembly, write_plan
        from cronista.story.service import StoryError

        settings = current_settings()
        setup_logging(settings.log_level)
        objectives = profile_objectives(settings)
        with open_db(settings.db_path) as db:
            try:
                plan = build_assembly(db, session, settings, target_min * 60, objectives)
            except StoryError as exc:
                typer.echo(f"erro: {exc}", err=True)
                raise typer.Exit(1) from exc
        path = write_plan(plan, out or SessionPaths.of(settings, session).assembly_dir, session)
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
        from cronista.story.script import load_script
        from cronista.story.service import StoryError

        settings = current_settings()
        setup_logging(settings.log_level)
        try:
            objectives = profile_objectives(settings)
            loaded = load_script(script) if script else None
            with open_db(settings.db_path) as db:
                report = mix_session(
                    db,
                    session,
                    settings,
                    loaded,
                    target_min * 60,
                    objectives,
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
        session: Annotated[
            int | None, typer.Argument(help="Sessão com segmentos (`cronista relevance`)")
        ] = None,
        project: Annotated[
            int | None,
            typer.Option("--projeto", help="Vídeo da série: todas as sessões do projeto, com um alvo só"),
        ] = None,
        script: Annotated[Path | None, typer.Option(help="roteiro.json validado")] = None,
        target_min: Annotated[float, typer.Option(help="Duração-alvo do vídeo, em minutos")] = 40.0,
        out: Annotated[
            Path | None, typer.Option(help="Base da exportação (padrão: data/export/montagem/<sessão>)")
        ] = None,
        acabamento: Annotated[
            bool,
            typer.Option("--acabamento", help="Inclui o plano de acabamento (sugestões viram marcadores)"),
        ] = False,
        serie: Annotated[str, typer.Option(help="Estilo de série para o acabamento")] = "",
    ) -> None:
        """Pacote para o Resolve: FCPXML multi-trilha, stems, SRT, marcadores em Lua e manifesto (Fase 6C)."""
        from cronista.export.pacote import export_montagem
        from cronista.montage import SessionPlanError
        from cronista.pipeline.stage import StageError
        from cronista.story.script import load_script
        from cronista.story.service import StoryError

        if (session is None) == (project is None):
            typer.echo("erro: informe a sessão ou --projeto (um dos dois)", err=True)
            raise typer.Exit(2)
        settings = current_settings()
        setup_logging(settings.log_level)
        try:
            objectives = profile_objectives(settings)
            loaded = load_script(script) if script else None
            style, library = load_style(settings, serie) if (acabamento or serie) else (None, None)
            with open_db(settings.db_path) as db:
                report = export_montagem(
                    db,
                    session,
                    settings,
                    loaded,
                    target_min * 60,
                    objectives,
                    out,
                    build_gate(settings),
                    style,
                    library,
                    project_id=project,
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

    @app.command("brand-check")
    def brand_check(
        serie: Annotated[str, typer.Option(help="Estilo de série (`brand-kit/series/<nome>.yaml`)")] = "",
        biblioteca: Annotated[
            bool, typer.Option("--biblioteca", help="Confere também o inventário da biblioteca pessoal")
        ] = False,
    ) -> None:
        """Valida o brand kit, o estilo da série e (opcional) a biblioteca pessoal (Fase 8A)."""
        from pydantic import ValidationError

        from cronista.finishing.brand import (
            brand_dir,
            check_brand_files,
            load_brand_kit,
            load_series_style,
            resolve_style,
        )
        from cronista.finishing.effects import EffectKind
        from cronista.finishing.library import check_brand_references, check_library, load_library

        settings = current_settings()
        setup_logging(settings.log_level)
        directory = brand_dir(settings.brand_dir)
        problems: list[str] = []
        try:
            brand = load_brand_kit(directory)
            style = load_series_style(directory, serie) if serie else None
        except (FileNotFoundError, ValueError, ValidationError) as exc:
            typer.echo(f"erro: {exc}", err=True)
            raise typer.Exit(1) from exc
        problems += check_brand_files(brand, directory, style)
        resolved = resolve_style(brand, style)
        typer.echo(f"brand kit {brand.name!r}" + (f", série {serie!r}" if serie else ""))
        for kind in EffectKind:
            p = resolved.policy(kind)
            typer.echo(
                f"  {kind.value:<16} {p.mode.value:<12} até {p.max_per_minute:g}/min, nota ≥ {p.min_score:g}"
            )
        typer.echo(f"  teto somado: {resolved.max_effects_per_minute:g} efeitos/min")
        if biblioteca:
            if settings.library_dir is None:
                problems.append("library_dir não configurado (defina em config/*.local.yaml)")
            else:
                try:
                    library = load_library(settings.library_dir)
                except (FileNotFoundError, ValueError, ValidationError) as exc:
                    typer.echo(f"erro: {exc}", err=True)
                    raise typer.Exit(1) from exc
                problems += check_library(library, settings.library_dir)
                problems += check_brand_references(resolved.brand, library)
                typer.echo(f"  biblioteca: {len(library.items)} itens")
        for problem in problems:
            typer.echo(f"problema: {problem}", err=True)
        if problems:
            raise typer.Exit(1)
        typer.echo("ok")

    @app.command("acabamento")
    def acabamento(
        session: Annotated[
            int | None, typer.Argument(help="Sessão com segmentos (`cronista relevance`)")
        ] = None,
        project: Annotated[
            int | None,
            typer.Option("--projeto", help="Vídeo da série: todas as sessões do projeto, com um alvo só"),
        ] = None,
        serie: Annotated[str, typer.Option(help="Estilo de série (`brand-kit/series/<nome>.yaml`)")] = "",
        target_min: Annotated[float, typer.Option(help="Duração-alvo do vídeo, em minutos")] = 40.0,
        out: Annotated[
            Path | None, typer.Option(help="Pasta de saída (padrão: data/acabamento/<sessão>)")
        ] = None,
    ) -> None:
        """Plano de acabamento: zoom, SFX, música e overlays dentro do orçamento por minuto (Fase 8B)."""
        from pydantic import ValidationError

        from cronista.finishing.service import build_finishing, write_finish_plan
        from cronista.story.service import StoryError

        if (session is None) == (project is None):
            typer.echo("erro: informe a sessão ou --projeto (um dos dois)", err=True)
            raise typer.Exit(2)
        settings = current_settings()
        setup_logging(settings.log_level)
        try:
            style, library = load_style(settings, serie)
            objectives = profile_objectives(settings)
        except (FileNotFoundError, ValueError, ValidationError) as exc:
            typer.echo(f"erro: {exc}", err=True)
            raise typer.Exit(1) from exc
        if library is None:
            typer.echo("aviso: library_dir não configurado; sem SFX nem música (só efeitos de imagem)")
        with open_db(settings.db_path) as db:
            try:
                plan = build_finishing(
                    db,
                    session,
                    settings,
                    style,
                    library,
                    target_min * 60,
                    objectives,
                    project_id=project,
                )
            except (StoryError, SessionPlanError) as exc:
                typer.echo(f"erro: {exc}", err=True)
                raise typer.Exit(1) from exc
        if project is not None:
            path = write_finish_plan(plan, out or series_finishing_dir(settings, project), f"serie-{project}")
        else:
            path = write_finish_plan(
                plan, out or SessionPaths.of(settings, session or 0).finishing_dir, session or 0
            )
        for kind, modes in sorted(plan.summary().items()):
            typer.echo(f"{kind:<16} " + ", ".join(f"{n} {mode}" for mode, n in sorted(modes.items())))
        for warning in plan.warnings:
            typer.echo(f"aviso: {warning}")
        typer.echo(str(path))

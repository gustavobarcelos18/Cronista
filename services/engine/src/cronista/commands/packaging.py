"""Embalagem: títulos, thumbnails, Shorts e pacote de publicação."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from cronista.commands.common import (
    Reframe,
    ShortChoice,
    current_settings,
)
from cronista.db.session import open_db
from cronista.gates import build_gate
from cronista.logging_setup import setup_logging
from cronista.paths import SessionPaths
from cronista.pipeline import StageError


def register(app: typer.Typer) -> None:
    @app.command("shorts")
    def shorts(
        session: Annotated[int, typer.Argument(help="Sessão com segmentos (`cronista relevance`)")],
        top: Annotated[int, typer.Option(help="Quantos candidatos listar")] = 10,
    ) -> None:
        """Lista os candidatos a Shorts: até 13 s, gancho nos 3 primeiros segundos (Fase 6D). Não grava nada:
        o manifesto é do `shorts-render`."""
        from cronista.shorts.candidates import ShortsParams
        from cronista.shorts.service import ShortsError, build_shorts

        settings = current_settings()
        setup_logging(settings.log_level)
        with open_db(settings.db_path) as db:
            try:
                found = build_shorts(db, session, ShortsParams(max_candidates=top))
            except ShortsError as exc:
                typer.echo(f"erro: {exc}", err=True)
                raise typer.Exit(1) from exc
        for n, c in enumerate(found, start=1):
            typer.echo(
                f"{n}. arquivo {c.file_id} {c.start_frame / 60:.1f}s: {c.duration_s:.1f} s, "
                f"nota {c.score:.2f}, "
                f"gancho ({c.hook_kind}) em {c.hook_offset_s:.1f} s; {c.reason}"
            )
        if not found:
            typer.echo(
                "nenhum candidato: faltam momentos com pico (marcador ou emoção) e gancho nos 3 s iniciais"
            )

    @app.command("shorts-render")
    def shorts_render(
        session: Annotated[int, typer.Argument(help="Sessão com segmentos (`cronista relevance`)")],
        top: Annotated[
            int,
            typer.Option(help="Quantos Shorts renderizar (o pacote pede 3 aprovados; sobra para rejeitar)"),
        ] = 5,
        serie: Annotated[str, typer.Option(help="Estilo de série (`brand-kit/series/<nome>.yaml`)")] = "",
        reframe: Annotated[
            Reframe, typer.Option(help="`desfoque` (gameplay inteira sobre fundo desfocado) ou `recorte`")
        ] = Reframe.DESFOQUE,
        focus_x: Annotated[float, typer.Option(help="Só no `recorte`: 0 = esquerda, 1 = direita")] = 0.5,
    ) -> None:
        """Renderiza os Shorts 9:16 com legenda gravada e margens seguras (Fase 9A)."""
        from pydantic import ValidationError

        from cronista.shorts.candidates import ShortsParams, short_key
        from cronista.shorts.render import ShortStyle
        from cronista.shorts.service import ShortsError, render_session_shorts

        settings = current_settings()
        setup_logging(settings.log_level)
        with open_db(settings.db_path) as db:
            try:
                package = render_session_shorts(
                    db,
                    session,
                    settings,
                    SessionPaths.of(settings, session).shorts_dir,
                    params=ShortsParams(max_candidates=top),
                    style=ShortStyle(reframe=reframe.value, focus_x=focus_x),
                    serie=serie,
                    gate=build_gate(settings),
                )
            except (ShortsError, FileNotFoundError, ValueError, ValidationError, StageError) as exc:
                typer.echo(f"erro: {exc}", err=True)
                raise typer.Exit(1) from exc
        for warning in package.warnings:
            typer.echo(f"aviso: {warning}")
        for c in package.candidates:
            clip = package.clips.get(short_key(c.file_id, c.start_frame, c.end_frame))
            typer.echo(f"{c.duration_s:.1f} s, nota {c.score:.2f}: {clip if clip else 'não renderizado'}")
        if not package.candidates:
            typer.echo("nenhum candidato a Short")

    @app.command("titulos")
    def titulos(
        session: Annotated[int, typer.Argument(help="Sessão com `story-pack.json` (`cronista story`)")],
    ) -> None:
        """Gera o `titulo-pack.json` compacto para o /titular escrever sugestões de título (Fase 9C)."""
        from cronista.packaging.service import TitleError, write_title_pack

        settings = current_settings()
        try:
            path = write_title_pack(
                SessionPaths.of(settings, session).story_dir, SessionPaths.of(settings, session).packaging_dir
            )
        except TitleError as exc:
            typer.echo(f"erro: {exc}", err=True)
            raise typer.Exit(1) from exc
        typer.echo(f"{path}\nAgora rode /titular no Claude Code com este pacote.")

    @app.command("titulos-import")
    def titulos_import(
        session: Annotated[int, typer.Argument(help="Sessão do pacote de títulos usado")],
        titles: Annotated[Path, typer.Argument(help="titulos.json escrito pelo /titular")],
    ) -> None:
        """Valida as sugestões (limite de 70 caracteres, repetição, clichê) e guarda `titulos.json`."""
        from cronista.packaging.service import TitleError, save_titles
        from cronista.packaging.titles import load_titles

        settings = current_settings()
        folder = SessionPaths.of(settings, session).packaging_dir
        try:
            report = save_titles(folder, load_titles(titles))
        except (ValueError, TitleError) as exc:
            typer.echo(f"erro: {exc}", err=True)
            for err in getattr(exc, "errors", []):
                typer.echo(f"erro: {err}", err=True)
            raise typer.Exit(1) from exc
        for warn in report.warnings:
            typer.echo(f"aviso: {warn}")
        for n, option in enumerate(report.titles, start=1):
            typer.echo(f"{n}. {option.text} ({len(option.text)})")

    @app.command("titulos-escolher")
    @app.command("titulo-escolher", deprecated=True, hidden=True)
    def titulo_escolher(
        session: Annotated[int, typer.Argument(help="Sessão (veja `cronista status`)")],
        sugestao: Annotated[int | None, typer.Option(help="Número da sugestão escolhida (1, 2, …)")] = None,
        texto: Annotated[
            str | None, typer.Option(help="Título do próprio criador (ou a sugestão editada)")
        ] = None,
    ) -> None:
        """Registra o título escolhido (só inserção); o texto do criador sempre vale mais que o sugerido."""
        from cronista.packaging.service import TitleError, record_title_choice

        settings = current_settings()
        with open_db(settings.db_path) as db:
            try:
                row = record_title_choice(
                    db,
                    session,
                    SessionPaths.of(settings, session).packaging_dir,
                    suggestion=sugestao,
                    text=texto,
                )
            except TitleError as exc:
                typer.echo(f"erro: {exc}", err=True)
                raise typer.Exit(1) from exc
        typer.echo(f"{row.origin}: {row.text}")

    @app.command("thumbnails")
    def thumbnails(
        session: Annotated[int, typer.Argument(help="Sessão com `story-pack.json` (`cronista story`)")],
        texto: Annotated[
            list[str] | None,
            typer.Option(
                help="Texto da thumbnail (repita para várias variações); ganha do sugerido pelo /titular"
            ),
        ] = None,
        dia: Annotated[
            int | None, typer.Option(help="Número do dia para o selo (decidido na edição)")
        ] = None,
        variacoes: Annotated[int, typer.Option(help="Quantas variações gerar (2 ou 3)", min=2, max=3)] = 3,
        serie: Annotated[str, typer.Option(help="Estilo de série (`brand-kit/series/<nome>.yaml`)")] = "",
    ) -> None:
        """Gera 2 a 3 variações de thumbnail a partir dos picos do vídeo e do modelo do brand kit (Fase 9B)."""  # noqa: E501
        from pydantic import ValidationError

        from cronista.story.service import StoryError
        from cronista.thumbnails.render import ThumbnailError
        from cronista.thumbnails.service import render_session_thumbnails

        settings = current_settings()
        setup_logging(settings.log_level)
        with open_db(settings.db_path) as db:
            try:
                package = render_session_thumbnails(
                    db,
                    session,
                    settings,
                    SessionPaths.of(settings, session).story_dir,
                    SessionPaths.of(settings, session).packaging_dir,
                    texts=texto,
                    day=dia,
                    count=variacoes,
                    serie=serie,
                    gate=build_gate(settings),
                )
            except (ThumbnailError, StoryError, FileNotFoundError, ValueError, ValidationError) as exc:
                typer.echo(f"erro: {exc}", err=True)
                raise typer.Exit(1) from exc
        for warning in package.warnings:
            typer.echo(f"aviso: {warning}")
        for item in package.items:
            v = item.variation
            typer.echo(
                f"{v.n}. arquivo {v.frame.file_id} em {v.frame.t_s:.1f}s ({v.frame.beat}), "
                f"nota {v.frame.score:.2f}, "
                f"texto {v.text!r} ({v.position}): {item.path}"
            )
        if package.items:
            typer.echo("Escolha com `cronista thumbnail-escolher <sessão> --variacao N`.")

    @app.command("thumbnails-escolher")
    @app.command("thumbnail-escolher", deprecated=True, hidden=True)
    def thumbnail_escolher(
        session: Annotated[int, typer.Argument(help="Sessão (veja `cronista status`)")],
        variacao: Annotated[int, typer.Option(help="Número da variação escolhida (1, 2, 3)")],
    ) -> None:
        """Registra a thumbnail escolhida (só inserção; a última vale)."""
        from cronista.thumbnails.render import ThumbnailError
        from cronista.thumbnails.service import record_thumbnail_choice

        settings = current_settings()
        with open_db(settings.db_path) as db:
            try:
                row = record_thumbnail_choice(
                    db, session, SessionPaths.of(settings, session).packaging_dir, variacao
                )
            except ThumbnailError as exc:
                typer.echo(f"erro: {exc}", err=True)
                raise typer.Exit(1) from exc
        typer.echo(f"variação {row.variation}: {row.file_name}")

    @app.command("shorts-status")
    def shorts_status(
        session: Annotated[
            int, typer.Argument(help="Sessão com Shorts renderizados (`cronista shorts-render`)")
        ],
    ) -> None:
        """Lista os Shorts da sessão com a chave, o MP4 e a decisão do criador (Fase 9D)."""
        from cronista.packaging.publish import PublishError, current_short_decisions, list_shorts

        settings = current_settings()
        with open_db(settings.db_path) as db:
            try:
                entries = list_shorts(SessionPaths.of(settings, session).shorts_dir, session)
            except PublishError as exc:
                typer.echo(f"erro: {exc}", err=True)
                raise typer.Exit(1) from exc
            decisions = current_short_decisions(db, session)
        for e in entries:
            state = decisions.get(e.key, "pendente")
            typer.echo(
                f"{e.key}  {state:9}  {e.duration_s:.1f} s, nota {e.score:.2f}  "
                f"{e.clip.name if e.clip else 'sem MP4'}"
            )
        if not entries:
            typer.echo("nenhum Short")

    @app.command("shorts-decidir")
    @app.command("short-decidir", deprecated=True, hidden=True)
    def short_decidir(
        session: Annotated[int, typer.Argument(help="Sessão (veja `cronista status`)")],
        short: Annotated[str, typer.Argument(help="Chave do Short (`cronista shorts-status`)")],
        decisao: Annotated[
            ShortChoice, typer.Option(help="`aprovado`, `rejeitado` ou `padrao` (volta a pendente)")
        ],
    ) -> None:
        """Aprova ou rejeita um Short (só inserção; a última decisão vale)."""
        from cronista.packaging.publish import PublishError, record_short_decision

        settings = current_settings()
        with open_db(settings.db_path) as db:
            try:
                row = record_short_decision(
                    db, session, SessionPaths.of(settings, session).shorts_dir, short, decisao.value
                )
            except PublishError as exc:
                typer.echo(f"erro: {exc}", err=True)
                raise typer.Exit(1) from exc
        typer.echo(f"{row.short_key}: {row.decision}")

    @app.command("pacote-publicacao")
    def pacote_publicacao(
        session: Annotated[int, typer.Argument(help="Sessão (veja `cronista status`)")],
        video: Annotated[
            Path | None, typer.Option(help="Vídeo da série renderizado no Resolve (copiado para a pasta)")
        ] = None,
        out: Annotated[
            Path | None, typer.Option(help="Pasta de saída (padrão: data/packaging/<sessão>/publicacao)")
        ] = None,
    ) -> None:
        """Reúne vídeo, Shorts aprovados, thumbnail e título numa pasta, com um LEIA-ME.md (Fase 9D)."""
        from cronista.packaging.publish import PublishError, build_publish_package

        settings = current_settings()
        with open_db(settings.db_path) as db:
            try:
                report = build_publish_package(
                    db,
                    session,
                    SessionPaths.of(settings, session).shorts_dir,
                    SessionPaths.of(settings, session).packaging_dir,
                    video=video,
                    out=out,
                )
            except PublishError as exc:
                typer.echo(f"erro: {exc}", err=True)
                raise typer.Exit(1) from exc
        for name in report.files:
            typer.echo(f"  {name}")
        for item in report.missing:
            typer.echo(f"falta: {item}")
        typer.echo(str(report.directory))
        if not report.ready:
            raise typer.Exit(2)

"""Relevância, história, revisão e roteiro."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import select

from cronista.commands.common import (
    TargetMinutes,
    _pick_media,
    current_settings,
    profile_objectives,
)
from cronista.db.models import Artifact
from cronista.db.session import open_db
from cronista.domain.frames import frame_to_seconds
from cronista.domain.models import StageResult
from cronista.logging_setup import setup_logging
from cronista.paths import SessionPaths, review_csv
from cronista.story.service import DEFAULT_TARGET_MIN
from cronista.video.models import build_video_models


def register(app: typer.Typer) -> None:
    @app.command("relevance")
    def relevance(
        session: Annotated[int, typer.Argument(help="Sessão analisada (`cronista analyze`)")],
        top: Annotated[int, typer.Option(help="Quantos candidatos mostrar por arquivo")] = 15,
    ) -> None:
        """Segmenta a sessão, dá nota explicável a cada trecho e grava os segmentos (Fase 4)."""
        from cronista.profiles import relevance_overrides
        from cronista.relevance.quality import top_candidates
        from cronista.relevance.service import RelevanceError, relevance_session

        settings = current_settings()
        setup_logging(settings.log_level)
        with open_db(settings.db_path) as db:
            try:
                results = relevance_session(db, session, overrides=relevance_overrides(settings))
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

    @app.command("series")
    def series() -> None:
        """Painel da série por projeto: horas gravadas e minutos de produto por sessão, e o acumulado."""
        from cronista.review.panel import series_panel_full

        settings = current_settings()
        with open_db(settings.db_path) as db:
            panel = series_panel_full(db, settings.relevance_overrides)
        for project in panel.projetos:
            typer.echo(
                f"{project.projeto} (projeto {project.projeto_id}): "
                f"{project.total_min} min, {project.situacao}"
            )
            typer.echo(f"{'sessão':>7}{'gravado (h)':>13}{'produto (min)':>15}{'acumulado (min)':>17}")
            for r in project.sessoes:
                typer.echo(f"{r.sessao:>7}{r.gravado_h:>13}{r.produto_min:>15}{r.acumulado_min:>17}")
        typer.echo(
            "estimativa: trechos relevantes (até 45 s cada) + farm em timelapse, com as suas decisões; "
            f"alvo do vídeo: {panel.minimo_min:.0f} a {panel.maximo_min:.0f} min"
        )

    @app.command("story")
    def story(
        session: Annotated[
            int | None, typer.Argument(help="Sessão com segmentos (`cronista relevance`)")
        ] = None,
        project: Annotated[
            int | None,
            typer.Option("--projeto", help="Vídeo da série: todas as sessões do projeto, com um alvo só"),
        ] = None,
        target_min: TargetMinutes = DEFAULT_TARGET_MIN,
        out: Annotated[Path | None, typer.Option(help="Pasta de saída (padrão: data/story/<sessão>)")] = None,
    ) -> None:
        """Capítulos, beats, objetivos e `story-pack.json` para o roteiro (Fases 5 e 5A)."""
        from cronista.story.service import (
            StoryError,
            anchor_session,
            build_series_story,
            build_story,
            write_pack,
        )

        if (session is None) == (project is None):
            typer.echo("erro: informe a sessão ou --projeto (um dos dois)", err=True)
            raise typer.Exit(2)

        settings = current_settings()
        setup_logging(settings.log_level)
        objectives = profile_objectives(settings)
        overrides = settings.relevance_overrides
        with open_db(settings.db_path) as db:
            try:
                result = (
                    build_series_story(db, project, target_min * 60, objectives, overrides)
                    if project is not None
                    else build_story(db, session or 0, target_min * 60, objectives, overrides)
                )
            except StoryError as exc:
                typer.echo(f"erro: {exc}", err=True)
                raise typer.Exit(1) from exc
        anchor_id = session or 0
        if project is not None:
            with open_db(settings.db_path) as db:
                anchor_id = anchor_session(db, project).id
        target = out or SessionPaths.of(settings, anchor_id).story_dir
        scope_file = target / "escopo.json"
        scope = "serie" if project is not None else "sessao"
        if scope_file.is_file() and json.loads(scope_file.read_text(encoding="utf-8")).get("escopo") != scope:
            typer.echo(
                "aviso: esta pasta tinha o pacote de outro escopo (sessão x série); o roteiro.json antigo "
                "pode não bater com o novo pacote (rode roteiro-import de novo)",
                err=True,
            )
        pack_path, voice_path = write_pack(target, result)
        scope_file.write_text(json.dumps({"escopo": scope, "projeto": project}), encoding="utf-8")
        for c in result.chapters:
            beats = ", ".join(f"{i.beat.value}" for i in c.items[:8])
            typer.echo(
                f"capítulo {c.number}: {len(c.items)} trechos, {c.allocated_s:.0f} s alocados ({beats})"
            )
        d = result.discovery
        typer.echo(
            f"objetivos: {d.confirmed} confirmados, {d.hypotheses} hipóteses, "
            f"{d.rejected} citações rejeitadas"
        )
        if project is not None:
            typer.echo(
                f"vídeo da série: o pacote mora na sessão âncora {anchor_id} (a última do projeto); "
                "use esse número em roteiro-import, titulos, thumbnails e shorts"
            )
        typer.echo(f"{pack_path}\n{voice_path}\nAgora rode /roteirizar no Claude Code com este pacote.")

    @app.command("revisao")
    def revisao(
        project: Annotated[int, typer.Argument(help="Projeto (veja `cronista status`)")] = 1,
        out: Annotated[Path | None, typer.Option(help="CSV de saída")] = None,
    ) -> None:
        """Fila de revisão: objetivos propostos ou incertos (nunca afirmados nem descartados)."""
        from cronista.story.objectives import export_review_csv, review_queue

        settings = current_settings()
        with open_db(settings.db_path) as db:
            items = review_queue(db, project)
            target = export_review_csv(items, out or review_csv(settings, project))
        typer.echo(f"{len(items)} itens para revisar: {target}")

    @app.command("roteiro-import")
    def roteiro_import(
        session: Annotated[int, typer.Argument(help="Sessão do story-pack usado")],
        script: Annotated[Path, typer.Argument(help="roteiro.json escrito pelo /roteirizar")],
    ) -> None:
        """Valida o roteiro (segmento, espaço livre, antecipação justificada, sinais de IA) e gera o SRT."""
        from cronista.story.script import load_script
        from cronista.story.service import ScriptSaveError, save_script

        settings = current_settings()
        folder = SessionPaths.of(settings, session).story_dir
        try:
            loaded = load_script(script)
            report = save_script(folder, loaded)
        except ValueError as exc:
            typer.echo(f"erro: {exc}", err=True)
            raise typer.Exit(1) from exc
        except ScriptSaveError as exc:
            typer.echo(f"erro: {exc}", err=True)
            for err in exc.errors:
                typer.echo(f"erro: {err}", err=True)
            raise typer.Exit(1) from exc
        for warn in report.warnings:
            typer.echo(f"aviso: {warn}")
        total = sum(line.est_s or 0 for line in report.lines)
        typer.echo(f"{len(report.lines)} falas, ~{total:.0f} s de narração; {folder / 'roteiro.srt'}")

    @app.command("roteiro-lint")
    def roteiro_lint(text: Annotated[Path, typer.Argument(help="Arquivo de texto ou roteiro.json")]) -> None:
        """Aponta sinais de texto de IA (padrões do /humanizar) numa narração."""
        from cronista.story.script import lint_text

        raw = text.read_text(encoding="utf-8-sig")
        pieces = (
            [line["text"] for line in json.loads(raw)["lines"]]
            if text.suffix == ".json"
            else raw.splitlines()
        )
        found = 0
        for n, piece in enumerate(pieces, start=1):
            flags = lint_text(piece)
            if flags:
                found += 1
                typer.echo(f"{n}: {', '.join(flags)} | {piece[:80]}")
        typer.echo(f"{found} de {len(pieces)} falas com sinais de IA")

    @app.command("broll-search")
    def broll_search(
        session: Annotated[int, typer.Argument(help="Número da sessão (veja `cronista status`)")],
        query: Annotated[
            str, typer.Argument(help='Texto em inglês, ex.: "a cave" ou "a sunset over the lake"')
        ],
        top: Annotated[int, typer.Option(help="Quantos resultados mostrar")] = 5,
        file: Annotated[
            str | None, typer.Option(help="Parte do nome do arquivo (padrão: o primeiro)")
        ] = None,
    ) -> None:
        """Busca B-roll da sessão por texto (precisa de `analyze` com `video_embedder` na configuração)."""
        import numpy as np

        from cronista.audio.events import load_stored_events
        from cronista.video import broll as broll_lib

        settings = current_settings()
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

"""Script de teste do Resolve (1C; plano mestre, seção 6.5): roda DE DENTRO do Resolve gratuito.

Instalar: copiar para `%APPDATA%\\Blackmagic Design\\DaVinci Resolve\\Support\\Fusion\\Scripts\\Utility\\` e rodar
em Workspace → Scripts → cronista_kit_teste. Também tenta rodar de fora (`python cronista_kit_teste.py`), o que no
gratuito costuma ser bloqueado: o resultado dessa tentativa também é uma resposta do spike.

Para cada passo grava OK ou FALHOU (com o motivo) em `resultado-script.txt`, ao lado do kit (`data/.../kit-resolve`).
Passar a pasta do kit em `KIT_DIR` (variável de ambiente) ou editar a constante abaixo.

⚠️ Os nomes da API (CreateProject, ImportMedia, ImportTimelineFromFile, AddMarker, SetLUT...) vêm de memória e da
documentação do `README.txt` de scripting do Resolve; este script existe para conferir quais existem no gratuito.
"""

from __future__ import annotations

import os
import traceback
from pathlib import Path

KIT_DIR = Path(os.environ.get("KIT_DIR", r"D:\EditorVideo\data\prod\kit-resolve"))
PROJECT = "Cronista-kit-teste"
RESULTS: list[str] = []


def step(name: str):
    """Decorador: executa o passo, anota OK/FALHOU e nunca derruba os passos seguintes."""

    def wrap(fn):
        try:
            detail = fn()
            RESULTS.append(f"OK      {name}" + (f" -> {detail}" if detail else ""))
            return detail
        except Exception as exc:  # noqa: BLE001 - o relatório é o produto
            RESULTS.append(f"FALHOU  {name}: {type(exc).__name__}: {exc}")
            RESULTS.append("        " + traceback.format_exc().strip().splitlines()[-2].strip())
            return None

    return wrap


def get_resolve():
    try:
        return resolve  # noqa: F821 - injetado pelo Resolve quando rodado pelo menu Scripts
    except NameError:
        import DaVinciResolveScript as dvr  # só existe se o Resolve configurou o PYTHONPATH

        return dvr.scriptapp("Resolve")


def main() -> None:
    state: dict = {}

    @step("conectar ao Resolve (de dentro: variável `resolve`; de fora: DaVinciResolveScript)")
    def _():
        state["resolve"] = get_resolve()
        if state["resolve"] is None:
            raise RuntimeError("scriptapp devolveu None (scripting externo bloqueado nesta edição?)")
        return state["resolve"].GetVersionString()

    if "resolve" not in state or state["resolve"] is None:
        return finish()
    r = state["resolve"]

    @step("criar projeto")
    def _():
        manager = r.GetProjectManager()
        state["project"] = manager.CreateProject(PROJECT) or manager.LoadProject(PROJECT)
        if not state["project"]:
            raise RuntimeError("CreateProject e LoadProject devolveram None")
        return PROJECT

    project = state.get("project")
    if not project:
        return finish()

    @step("configurar 1920x1080 a 60 fps")
    def _():
        ok = [
            project.SetSetting("timelineResolutionWidth", "1920"),
            project.SetSetting("timelineResolutionHeight", "1080"),
            project.SetSetting("timelineFrameRate", "60"),
        ]
        return f"SetSetting={ok}; fps lido={project.GetSetting('timelineFrameRate')}"

    pool = project.GetMediaPool()

    @step("importar mídia (H.264, HEVC, overlay com alfa)")
    def _():
        names = ["A_h264.mp4", "B_h264.mp4", "C_hevc.mp4", "overlay_alfa.mov"]
        items = pool.ImportMedia([str(KIT_DIR / "clips" / n) for n in names])
        state["items"] = items or []
        if not items:
            raise RuntimeError("ImportMedia não devolveu nenhum item")
        return f"{len(items)} de {len(names)} itens"

    @step("criar timeline e anexar clipe H.264")
    def _():
        timeline = pool.CreateEmptyTimeline("kit-script")
        state["timeline"] = timeline
        appended = pool.AppendToTimeline(state["items"][:1])
        return f"timeline={bool(timeline)}, anexados={len(appended or [])}"

    @step("marcadores coloridos com nome e nota (AddMarker)")
    def _():
        timeline = state["timeline"]
        results = [
            timeline.AddMarker(frame, color, name, f"nota de {name}", 1, f"{name}|teste")
            for frame, color, name in ((60, "Blue", "Momento"), (180, "Red", "Morte"), (300, "Green", "Conquista"))
        ]
        return f"AddMarker={results}; lidos={len(timeline.GetMarkers() or {})}"

    @step("LUT no primeiro clipe do timeline (SetLUT)")
    def _():
        clip = state["timeline"].GetItemListInTrack("video", 1)[0]
        ok = clip.SetLUT(1, str(KIT_DIR / "teste.cube"))
        return f"SetLUT={ok}"

    for fcpxml in ("01-basico", "02-recursos", "03-audio"):

        @step(f"importar {fcpxml}.fcpxml (ImportTimelineFromFile)")
        def _(name=fcpxml):
            timeline = pool.ImportTimelineFromFile(str(KIT_DIR / f"{name}.fcpxml"), {"importSourceClips": True})
            if not timeline:
                raise RuntimeError("devolveu None: o Resolve recusou o arquivo (veja o console do Resolve)")
            tracks = {k: timeline.GetTrackCount(k) for k in ("video", "audio")}
            return f"timeline={timeline.GetName()!r} trilhas={tracks} fps={timeline.GetSetting('timelineFrameRate')}"

    @step("importar legenda SRT na timeline atual")
    def _():
        ok = pool.ImportMedia([str(KIT_DIR / "roteiro.srt")])
        return f"ImportMedia(srt)={bool(ok)} (o Resolve trata SRT como item de legenda; conferir na página Edit)"

    finish()


def finish() -> None:
    out = KIT_DIR / "resultado-script.txt"
    out.write_text("\n".join(RESULTS) + "\n", encoding="utf-8")
    print("\n".join(RESULTS))
    print(f"\nRelatório gravado em {out}")


if __name__ == "__main__":
    main()

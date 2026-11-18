"""Aplica o plano de acabamento na exportação (Fase 8D): renderiza, resolve a biblioteca, descreve.

Chamado por `export_montagem` depois da mixagem (a música com ducking precisa do stem de voz). Devolve o que o
FCPXML leva (`FinishLayers`), o stem A4, o Lua do LUT e o texto do manifesto e do LEIA-ME, com o
**como desfazer** cada efeito. Nada aqui altera a gravação: tudo fica em trilhas acima (V2, V4, A4,
A5) ou em marcadores.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from cronista.assembly.plan import EditPlan
from cronista.config import Settings
from cronista.export.finish_fcpxml import APPLIED, AudioFile, FinishLayers
from cronista.finishing.brand import ResolvedStyle
from cronista.finishing.effects import EffectKind, EffectMode
from cronista.finishing.library import Library
from cronista.finishing.plan import FPS, FinishItem, FinishPlan
from cronista.finishing.render.audio import audio_frames, render_music_stem
from cronista.finishing.render.overlay import counter_text, render_overlays
from cronista.finishing.render.video import render_video_effects, source_window
from cronista.pipeline.gpu import GpuGate

RENDERED = frozenset({EffectKind.ZOOM, EffectKind.SHAKE, EffectKind.CONTADOR_MORTES, EffectKind.MUSICA})
AUDIO_KINDS = frozenset({EffectKind.SFX, EffectKind.SFX_MEME, EffectKind.MUSICA})

UNDO: dict[EffectKind, str] = {
    EffectKind.ZOOM: "desative ou apague o clipe da V2 nesse trecho; a gravação na V1 não foi tocada",
    EffectKind.SHAKE: "desative ou apague o clipe da V2 nesse trecho; a gravação na V1 não foi tocada",
    EffectKind.CONTADOR_MORTES: "desative ou apague o clipe da V4",
    EffectKind.SFX: "desative ou apague o clipe da A5",
    EffectKind.SFX_MEME: "desative ou apague o clipe da A5",
    EffectKind.MUSICA: "desative a A4 (ou o clipe da música, no modo editável)",
    EffectKind.COR_LUT: "no Resolve, página Color: clique com o botão direito no nó 1 → Remove LUT",
}


@dataclass
class FinishArtifacts:
    layers: FinishLayers
    music_stem: Path | None = None
    lut_lua: Path | None = None
    effects: list[dict[str, object]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def lua_lut(lut_path: Path) -> str:
    """Lua de uma linha: LUT no nó 1 de cada clipe da V1 e da V2 (sem `io`, `dofile` nem `require`).

    A V2 leva os efeitos (zoom e shake, editáveis ou renderizados): sem LUT nela, a cor "pula" durante cada
    efeito, porque o clipe da V2 cobre a V1 já corrigida.

    ⚠️ `SetLUT` do scripting do Resolve ainda não foi conferido na versão gratuita (plano 6.5).
    """
    escaped = lut_path.resolve().as_posix().replace("\\", "\\\\").replace('"', '\\"')
    return (
        "local t = resolve:GetProjectManager():GetCurrentProject():GetCurrentTimeline(); local n = 0; "
        "for _, track in ipairs({1, 2}) do "
        'for _, i in ipairs(t:GetItemListInTrack("video", track)) do '
        f'if i:SetLUT(1, "{escaped}") then n = n + 1 end end end; '
        'print("LUT aplicada em " .. n .. " clipes")'
    )


def _rgba(hex_color: str) -> str:
    value = hex_color.lstrip("#")
    return " ".join(f"{int(value[i : i + 2], 16) / 255:.3f}" for i in (0, 2, 4)) + " 1"


def apply_finishing(
    finish: FinishPlan,
    plan: EditPlan,
    masters: Mapping[int, Path],
    style: ResolvedStyle,
    library: Library | None,
    settings: Settings,
    cache_dir: Path,
    directory: Path,
    brand_directory: Path | None = None,
    gate: GpuGate | None = None,
) -> FinishArtifacts:
    """Renderiza o que o plano pede (em `cache_dir`, que sobrevive entre versões) e monta as camadas."""
    visual = style.brand.visual
    warnings: list[str] = []
    video = render_video_effects(finish, plan, masters, cache_dir / "efeitos", settings, gate)
    overlays = render_overlays(finish, visual, brand_directory, cache_dir / "overlays", settings, gate)
    warnings += [*video.warnings, *overlays.warnings]

    rendered = {**video.clips, **overlays.clips}
    frames: dict[str, int] = {}
    for item in finish.items:
        if item.id in video.clips and (window := source_window(plan, item)) is not None:
            frames[item.id] = window.frames
        elif item.id in overlays.clips:
            frames[item.id] = item.frames

    audio_files, audio_warnings = _library_audio(finish, library, settings.library_dir)
    warnings += audio_warnings
    audio: dict[str, AudioFile] = {}
    for asset_id, path in sorted(audio_files.items()):
        try:
            audio[asset_id] = AudioFile(path, audio_frames(path))
        except (RuntimeError, OSError) as exc:  # formato que a libsndfile não lê, arquivo corrompido
            warnings.append(f"áudio {asset_id!r}: não consegui ler {path.name} ({exc}); ignorado")
    audio_files = {i: p for i, p in audio_files.items() if i in audio}
    for item in finish.items:
        known = audio.get(item.asset_id or "")
        if item.kind == EffectKind.MUSICA and item.mode in APPLIED and known and known.frames < item.frames:
            warnings.append(
                f"{item.id}: a trilha {item.asset_id!r} ({known.frames / FPS:.0f} s) é mais curta que o "
                f"capítulo ({item.frames / FPS:.0f} s); o resto fica sem música"
            )

    stems = directory / "stems"
    music_stem, music_warnings = render_music_stem(
        finish, audio_files, stems / "A2-voz.wav", stems / "A4-musica.wav", plan.total_frames, settings, gate
    )
    warnings += music_warnings

    texts = {
        i.id: counter_text(visual.death_counter, int(i.params.get("ordem", 0)))
        for i in finish.items
        if i.kind == EffectKind.CONTADOR_MORTES and i.mode == EffectMode.EDITAVEL
    }
    layers = FinishLayers(
        finish,
        rendered=rendered,
        rendered_frames=frames,
        audio=audio,
        texts=texts,
        font=visual.fonts.title,
        font_color=_rgba(visual.palette.text),
    )
    lut_lua, lut_warnings = _lut(finish, brand_directory, directory)
    warnings += lut_warnings
    artifacts = FinishArtifacts(layers, music_stem, lut_lua, [], warnings)
    artifacts.effects = describe_effects(finish, artifacts)
    return artifacts


def _library_audio(
    finish: FinishPlan, library: Library | None, library_dir: Path | None
) -> tuple[dict[str, Path], list[str]]:
    """Arquivo de cada item de áudio que o plano usa em modo aplicado."""
    found: dict[str, Path] = {}
    warnings: list[str] = []
    wanted = sorted(
        {i.asset_id for i in finish.items if i.kind in AUDIO_KINDS and i.mode in APPLIED and i.asset_id}
    )
    for asset_id in wanted:
        entry = library.get(asset_id) if library else None
        if entry is None or library_dir is None:
            warnings.append(f"áudio {asset_id!r}: biblioteca não configurada ou item ausente")
            continue
        path = (library_dir / entry.file).resolve()
        if not path.is_file() or not path.is_relative_to(library_dir.resolve()):
            warnings.append(f"áudio {asset_id!r}: arquivo {entry.file!r} não encontrado na biblioteca")
            continue
        found[asset_id] = path
    return found, warnings


def _lut(finish: FinishPlan, brand_directory: Path | None, directory: Path) -> tuple[Path | None, list[str]]:
    """Copia o `.cube` para o pacote e escreve o Lua que o aplica (só no modo `editavel`)."""
    items = [i for i in finish.items if i.kind == EffectKind.COR_LUT and i.mode == EffectMode.EDITAVEL]
    if not items:
        return None, []
    name = str(items[0].params.get("lut", ""))
    missing = [f"LUT {name!r} não encontrado no brand kit; nada aplicado"]
    if not name or brand_directory is None:
        return None, missing
    source = (brand_directory / name).resolve()
    if not source.is_file() or not source.is_relative_to(brand_directory.resolve()):
        return None, missing
    target_dir = directory / "luts"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    shutil.copyfile(source, target)
    lua = directory / "lut-aplicar.lua"
    lua.write_text(lua_lut(target) + "\n", encoding="utf-8")
    return lua, []


def _how(item: FinishItem, artifacts: FinishArtifacts) -> str:
    layers = artifacts.layers
    if item.mode == EffectMode.SUGERIR:
        return "só marcador na timeline; aplicar é decisão sua"
    where = {
        EffectKind.ZOOM: "V2",
        EffectKind.SHAKE: "V2",
        EffectKind.CONTADOR_MORTES: "V4",
        EffectKind.SFX: "A5",
        EffectKind.SFX_MEME: "A5",
        EffectKind.MUSICA: "A4",
        EffectKind.COR_LUT: "Color",
    }.get(item.kind, "")
    note = f"{item.mode.value} na {where}" if where else item.mode.value
    needs_render = item.mode == EffectMode.RENDERIZADO and item.kind in RENDERED
    if (
        needs_render
        and item.id not in layers.rendered
        and not (item.kind == EffectKind.MUSICA and artifacts.music_stem)
    ):
        note += " (não gerado: veja os avisos)"
    return note


def describe_effects(finish: FinishPlan, artifacts: FinishArtifacts) -> list[dict[str, object]]:
    """Uma linha por item do plano, para o `manifesto.json` e o LEIA-ME (o quê, onde e como desfazer)."""
    rows: list[dict[str, object]] = []
    for item in sorted(finish.items, key=lambda i: (i.start, i.id)):
        rows.append(
            {
                "id": item.id,
                "momento": item.moment_id,
                "efeito": item.kind.value,
                "modo": item.mode.value,
                "inicio_s": round(item.start / FPS, 2),
                "duracao_s": round(item.frames / FPS, 2),
                "item": item.asset_id,
                "como": _how(item, artifacts),
                "desfazer": "apague o marcador"
                if item.mode == EffectMode.SUGERIR
                else UNDO.get(item.kind, ""),
            }
        )
    return rows


def leia_me_section(finish: FinishPlan, artifacts: FinishArtifacts) -> str:
    """Seção do LEIA-ME sobre o acabamento: o que foi aplicado e como desfazer, por tipo de efeito."""
    counts = finish.summary()
    lines = ["", "## Acabamento (Fase 8)", ""]
    if not counts:
        return "\n".join(
            [*lines, "Nenhum efeito foi aplicado (nada passou da nota mínima ou do orçamento).", ""]
        )
    for kind, modes in sorted(counts.items()):
        what = ", ".join(f"{n} em modo {mode}" for mode, n in sorted(modes.items()))
        undo = UNDO.get(EffectKind(kind), "")
        lines.append(f"- **{kind}**: {what}." + (f" Desfazer: {undo}." if undo else ""))
    lines += [
        "",
        "Tudo fica **acima** da gravação (V2, V4, A4, A5) ou em marcadores; V1 e os stems A1/A2 não mudam.",
        "O detalhe de cada efeito (instante, arquivo, como desfazer) está em `manifesto.json` (`efeitos`).",
    ]
    if artifacts.lut_lua is not None:
        lines.append(
            f"- LUT: cole o conteúdo de `{artifacts.lut_lua.name}` no Console do Resolve (a timeline aberta);"
            " o arquivo `.cube` está em `luts/`."
        )
    lines.append("")
    return "\n".join(lines)


def _file_stamp(path: Path) -> str:
    """Tamanho e data de modificação: barato e suficiente para notar que um arquivo grande mudou."""
    try:
        stat = path.stat()
    except OSError:
        return "ausente"
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def inputs_digest(
    finish: FinishPlan,
    style: ResolvedStyle,
    brand_directory: Path | None,
    library: Library | None,
    library_dir: Path | None,
) -> str:
    """Impressão digital do que, além do plano, muda o resultado renderizado.

    Vale o brand kit (cores, fontes, texto do contador), os arquivos que ele referencia (LUT, fontes) e os da
    biblioteca que o plano usa. Entra no hash da exportação: sem isso, trocar a fonte ou o `.cube` e
    re-exportar devolveria a versão antiga.
    """
    h = hashlib.sha256(style.brand.model_dump_json().encode())
    visual = style.brand.visual
    if brand_directory is not None:
        for relative in sorted({*visual.fonts.files, *([visual.lut] if visual.lut else [])}):
            h.update(f"{relative}={_file_stamp(brand_directory / relative)}".encode())
    if library is not None and library_dir is not None:
        for asset_id in sorted({i.asset_id for i in finish.items if i.asset_id}):
            entry = library.get(asset_id)
            if entry is not None:
                h.update(
                    f"{asset_id}={entry.model_dump_json()}={_file_stamp(library_dir / entry.file)}".encode()
                )
    return h.hexdigest()

"""Música e SFX (Fase 8C): duração dos arquivos da biblioteca e a trilha A4 com ducking sob a voz.

Em modo `renderizado`, as músicas do plano viram **um stem A4 do tamanho da timeline**, cortado nos compassos
inteiros que o plano escolheu, com fade e `sidechaincompress` contra o stem de voz (A2): a música abaixa
quando há fala. Em modo `editavel` não há render: o FCPXML leva os arquivos com volume fixo (ver `export/`).
A parte pura monta o grafo de filtros; o executor roda o FFmpeg e só foi exercitado com ele em `prod`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import soundfile

from cronista.config import Settings
from cronista.domain.frames import FPS
from cronista.finishing.effects import EffectKind, EffectMode
from cronista.finishing.plan import FinishItem, FinishPlan
from cronista.media.ffmpeg import run_ffmpeg
from cronista.pipeline.gpu import GpuGate, wait_until_free

MUSIC_BED_DB = -20.0
"""Nível da música antes do ducking (palpite conservador, ajustado ouvindo um vídeo real)."""
FADE_IN_S, FADE_OUT_S = 0.5, 1.5
SAMPLE_RATE = 48000


def audio_frames(path: Path) -> int:
    """Duração do arquivo em quadros de 60 fps (arredondada para baixo: nunca passa do fim do arquivo)."""
    info = soundfile.info(str(path))
    return int(info.frames * FPS // info.samplerate)


@dataclass(frozen=True)
class MusicClip:
    path: Path
    start: int
    """Quadro da timeline onde a música entra."""
    frames: int


def _ms(frames: int) -> int:
    return round(frames * 1000 / FPS)


def music_filtergraph(clips: Sequence[MusicClip], total_frames: int, bed_db: float = MUSIC_BED_DB) -> str:
    """Entradas `0..N-1` = músicas, `N` = stem de voz. Saída `[out]` com `total_frames` quadros exatos."""
    if not clips:
        raise ValueError("sem músicas para mixar")
    voice = len(clips)
    parts: list[str] = []
    for n, clip in enumerate(clips):
        seconds = clip.frames / FPS
        fade_in, fade_out = min(FADE_IN_S, seconds / 4), min(FADE_OUT_S, seconds / 4)
        parts.append(
            f"[{n}:a]aresample={SAMPLE_RATE},aformat=channel_layouts=stereo,"
            f"atrim=duration={seconds:.6f},asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d={fade_in:.3f},afade=t=out:st={seconds - fade_out:.3f}:d={fade_out:.3f},"
            f"volume={bed_db:g}dB,adelay={_ms(clip.start)}|{_ms(clip.start)}[m{n}]"
        )
    mixed = "".join(f"[m{n}]" for n in range(len(clips)))
    parts.append(
        f"{mixed}amix=inputs={len(clips)}:normalize=0:duration=longest[bed]"
        if len(clips) > 1
        else "[m0]anull[bed]"
    )
    parts.append(f"[{voice}:a]aresample={SAMPLE_RATE},aformat=channel_layouts=stereo[voice]")
    parts.append("[bed][voice]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=500[ducked]")
    total_s = total_frames / FPS
    parts.append(f"[ducked]apad=whole_dur={total_s:.6f},atrim=duration={total_s:.6f}[out]")
    return ";".join(parts)


def music_items(finish: FinishPlan, mode: EffectMode = EffectMode.RENDERIZADO) -> list[FinishItem]:
    return sorted(
        (i for i in finish.items if i.kind == EffectKind.MUSICA and i.mode == mode and i.asset_id),
        key=lambda i: (i.start, i.id),
    )


def render_music_stem(
    finish: FinishPlan,
    files: Mapping[str, Path],
    voice_stem: Path,
    target: Path,
    total_frames: int,
    settings: Settings,
    gate: GpuGate | None = None,
) -> tuple[Path | None, list[str]]:
    """Stem A4 (WAV 24 bits, 48 kHz, estéreo) ou `None` se não há música renderizada. Devolve avisos."""
    warnings: list[str] = []
    clips: list[MusicClip] = []
    for item in music_items(finish):
        path = files.get(item.asset_id or "")
        if path is None or not path.is_file():
            warnings.append(f"{item.id}: arquivo da música {item.asset_id!r} não encontrado; ignorada")
            continue
        clips.append(MusicClip(path, item.start, min(item.frames, max(0, total_frames - item.start))))
    clips = [c for c in clips if c.frames >= 2]
    if not clips:
        return None, warnings
    if not voice_stem.is_file():
        warnings.append("música renderizada precisa do stem de voz (A2) para o ducking; ignorada")
        return None, warnings
    if gate is not None:
        wait_until_free(gate, settings.gpu_poll_seconds, etapa="musica", arquivo=target.name)
    graph = music_filtergraph(clips, total_frames)
    inputs: list[str] = []
    for clip in clips:
        inputs += ["-i", str(clip.path)]
    run_ffmpeg(
        settings,
        [*inputs, "-i", str(voice_stem), "-filter_complex", graph, "-map", "[out]",
         "-c:a", "pcm_s24le", "-ar", str(SAMPLE_RATE), str(target)],
    )  # fmt: skip
    return target, warnings

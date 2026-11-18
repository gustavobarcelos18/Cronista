"""Vídeo com o **relógio de parede escrito nos quadros**: verdade-terreno para o tempo dos marcadores.

O tempo dos marcadores é reconstruído do diário (relógio do toque - início - pausas). Para provar que isso cai
no quadro certo, e não só que a conta fecha, o vídeo mostra o relógio de parede de cada instante gravado:

- metade esquerda do quadro: rampa lenta, 0..`WALL_SPAN_S` s em todo o brilho (resolução ~80 ms);
- metade direita: dente de serra de 1 s (resolução ~4 ms, mas ambígua módulo 1 s).

As duas juntas dão o relógio de parede com erro de poucos ms. Uma gravação com pausa é montada **recortando**
o trecho pausado do relógio de parede, como o OBS faz: o arquivo não tem o intervalo, mas os quadros seguintes
mostram o relógio de depois da pausa. `wall_time_at(arquivo, t_mídia)` lê o relógio do quadro nesse instante.

Os valores ficam em [16, 235] (faixa limitada do H.264) para o brilho decodificado ser proporcional ao valor.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from cronista.config import Settings
from cronista.media.ffmpeg import run_ffmpeg

WALL_SPAN_S = 20.0
SIZE = "320x180"
_AUDIO_TONES = (440, 660, 880)


def _segment(settings: Settings, out: Path, wall_start: int, wall_end: int) -> None:
    duration = wall_end - wall_start
    ramp = f"16+219*(T+{wall_start})/{WALL_SPAN_S}"
    saw = f"16+219*mod(T+{wall_start},1)"
    geq = f"geq=lum='if(lt(X,W/2),{ramp},{saw})':cb=128:cr=128"
    args = ["-f", "lavfi", "-i", f"color=c=black:s={SIZE}:r=60:d={duration}"]
    for tone in _AUDIO_TONES:
        args += ["-f", "lavfi", "-i", f"sine=frequency={tone}:duration={duration}"]
    args += ["-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:a"]
    args += ["-vf", f"format=yuv420p,{geq}", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "10"]
    args += ["-pix_fmt", "yuv420p", "-r", "60", "-g", "30", "-c:a", "aac"]
    run_ffmpeg(settings, [*args, str(out)])


def make_timecoded(
    settings: Settings, out: Path, wall_segments: Sequence[tuple[int, int]], *, interrupted: bool = False
) -> None:
    """Grava `out` com os trechos de relógio de parede dados, em ordem (segundos inteiros).

    `[(0, 4), (9, 14)]` = gravou 0 a 4 s, ficou pausado até 9 s e gravou até 14 s: o arquivo tem 9 s.
    `interrupted` gera um MP4 fragmentado com o final cortado (queda), como o Hybrid MP4 do OBS.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    try:
        for index, (start, end) in enumerate(wall_segments):
            part = out.with_name(f".{out.stem}-parte{index}.mp4")
            _segment(settings, part, start, end)
            parts.append(part)
        listing = out.with_name(f".{out.stem}-lista.txt")
        listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
        parts.append(listing)
        flags = "frag_keyframe+empty_moov" if interrupted else "+faststart"
        concat = ["-f", "concat", "-safe", "0", "-i", str(listing), "-map", "0", "-c", "copy"]
        run_ffmpeg(settings, [*concat, "-movflags", flags, str(out)])
    finally:
        for part in parts:
            part.unlink(missing_ok=True)
    if interrupted:  # corta o final no lugar, sem ler o conteúdo: é a "queda"
        with out.open("r+b") as handle:
            handle.truncate(int(out.stat().st_size * 0.85))


def wall_time_at(settings: Settings, video: Path, media_s: float) -> float:
    """Relógio de parede mostrado no quadro do instante `media_s` do arquivo (erro de alguns ms)."""
    graph = "split[a][b];[a]crop=iw/2:ih:0:0,scale=1:1[l];[b]crop=iw/2:ih:iw/2:0,scale=1:1[r];[l][r]hstack"
    cmd = [
        settings.ffmpeg, "-v", "error", "-ss", f"{media_s:.3f}", "-i", str(video), "-frames:v", "1",
        "-vf", graph, "-pix_fmt", "gray", "-f", "rawvideo", "-",
    ]  # fmt: skip
    data = subprocess.run(cmd, capture_output=True, check=True).stdout
    if len(data) < 2:
        raise ValueError(f"nenhum quadro em {media_s:.3f}s de {video.name}")
    coarse = data[0] / 255 * WALL_SPAN_S
    fraction = data[1] / 255
    return round(coarse - fraction) + fraction

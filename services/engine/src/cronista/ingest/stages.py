"""Etapas da ingestão: normalize → (proxy, audio)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from cronista.config import Settings
from cronista.domain.models import MediaProbe, StageResult
from cronista.ingest.ffmpeg import probe_media
from cronista.media.ffmpeg import run_ffmpeg
from cronista.pipeline.stage import Stage, StageContext, StageError

MIN_AUDIO_TRACKS = 3  # 1 = mix, 2 = jogo, 3 = microfone (plano mestre, seção 2)


class NormalizeStage:
    """Valida o arquivo e o deixa pronto: remux se interrompido, conversão se 10-bit, rejeita fps errado."""

    name = "normalize"
    version = "1"
    needs: tuple[str, ...] = ()
    uses_gpu = False

    def params(self, settings: Settings) -> dict[str, Any]:
        return {"expected_fps": settings.expected_fps}

    def run(self, ctx: StageContext) -> StageResult:
        s = ctx.settings
        media = ctx.media_path
        warnings: list[str] = []
        actions: list[str] = []
        files: list[str] = []

        probe = probe_media(s, media)
        if probe.interrupted:
            # `-map 0` é obrigatório: sem ele o FFmpeg copia só uma faixa de áudio e perde as faixas 2 e 3.
            remuxed = ctx.out_dir / "remuxed.mp4"
            run_ffmpeg(
                s, ["-i", str(media), "-map", "0", "-c", "copy", "-movflags", "+faststart", str(remuxed)]
            )
            media = remuxed
            files.append(str(remuxed))
            actions.append("remux")
            warnings.append("Arquivo interrompido: remux sem recodificar (-map 0 -c copy)")
            probe = probe_media(s, media)
            if probe.interrupted or probe.video_codec is None:
                raise StageError("arquivo ilegível mesmo após o remux")

        if probe.fps != s.expected_fps:
            raise StageError(
                f"fps {probe.fps} rejeitado: a série usa {s.expected_fps} exatos (OBS: FPS comuns → 60)"
            )
        if probe.audio_streams < MIN_AUDIO_TRACKS:
            raise StageError(
                f"{probe.audio_streams} faixa(s) de áudio; esperado {MIN_AUDIO_TRACKS} "
                "(1 mix, 2 jogo, 3 microfone)"
            )
        if probe.video_codec != "h264":
            warnings.append(
                f"Codec {probe.video_codec}: o padrão é H.264 (HEVC só depois do spike do Resolve)"
            )

        if probe.bit_depth > 8:
            converted = ctx.out_dir / "8bit.mp4"
            run_ffmpeg(
                s,
                ["-i", str(media), "-map", "0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                 "-pix_fmt", "yuv420p", "-c:a", "copy", str(converted)],
            )  # fmt: skip
            media = converted
            files.append(str(converted))
            actions.append("convert_8bit")
            warnings.append(f"Vídeo {probe.bit_depth}-bit convertido para 8-bit (Resolve gratuito)")
            probe = probe_media(s, media)

        return StageResult(
            files=files,
            data={"media": str(media), "actions": actions, "probe": probe.model_dump()},
            warnings=warnings,
        )


def _media_of(ctx: StageContext) -> Path:
    return Path(str(ctx.inputs["normalize"].data["media"]))


class ProxyStage:
    """Proxy 360p H.264 + AAC com uma faixa só (o mix, faixa 1) e `faststart`, para tocar no navegador."""

    name = "proxy"
    version = "1"
    needs: tuple[str, ...] = ("normalize",)
    uses_gpu = False

    def params(self, settings: Settings) -> dict[str, Any]:
        return {"height": settings.proxy_height, "crf": settings.proxy_crf}

    def run(self, ctx: StageContext) -> StageResult:
        out = ctx.out_dir / "proxy.mp4"
        run_ffmpeg(
            ctx.settings,
            ["-i", str(_media_of(ctx)), "-map", "0:v:0", "-map", "0:a:0",
             "-vf", f"scale=-2:{ctx.settings.proxy_height}", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", str(ctx.settings.proxy_crf), "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
             str(out)],
        )  # fmt: skip
        return StageResult(files=[str(out)], data={"proxy": str(out)})


AUDIO_TRACKS: tuple[tuple[str, int], ...] = (("game", 1), ("mic", 2))
"""Rótulo → índice da faixa entre as de áudio (0 = mix, que nunca é extraído nem analisado)."""


def audio_extract_args(media: Path, outputs: Sequence[tuple[int, Path]]) -> list[str]:
    """Uma leitura só do master, uma saída WAV por faixa.

    `-rf64 auto`: o WAV comum tem cabeçalho de 32 bits e para em 4 GB; uma faixa estéreo 48 kHz 16-bit
    passa disso em ~6,2 h de gravação. Acima do limite o FFmpeg escreve RF64; abaixo, continua WAV comum.
    """
    args = ["-i", str(media)]
    for index, out in outputs:
        args += ["-map", f"0:a:{index}", "-c:a", "pcm_s16le", "-rf64", "auto", str(out)]
    return args


class AudioStage:
    """WAV das faixas 2 (jogo) e 3 (microfone), cópias de trabalho regeneráveis do master."""

    name = "audio"
    version = "2"  # 2: RF64 acima de 4 GB e leitura única do master
    needs: tuple[str, ...] = ("normalize",)
    uses_gpu = False

    def params(self, settings: Settings) -> dict[str, Any]:
        return {"tracks": [label for label, _ in AUDIO_TRACKS]}

    def run(self, ctx: StageContext) -> StageResult:
        outputs = {label: ctx.out_dir / f"{label}.wav" for label, _ in AUDIO_TRACKS}
        run_ffmpeg(
            ctx.settings,
            audio_extract_args(_media_of(ctx), [(index, outputs[label]) for label, index in AUDIO_TRACKS]),
        )
        data = {label: str(path) for label, path in outputs.items()}
        return StageResult(files=list(data.values()), data=data)


def ingest_stages() -> list[Stage]:
    """Ordem topológica das etapas de ingestão."""
    return [NormalizeStage(), ProxyStage(), AudioStage()]


__all__ = [
    "AUDIO_TRACKS",
    "AudioStage",
    "MediaProbe",
    "NormalizeStage",
    "ProxyStage",
    "audio_extract_args",
    "ingest_stages",
]

"""Kit de teste do Resolve gratuito (1C, tarefa 1; plano mestre, seção 6.5).

Gera em `data/kit-resolve/` (nunca versionado) o material para o roteiro `integrations/resolve/ROTEIRO.md`:
clipes sintéticos H.264/HEVC 8-bit a 60 fps com três faixas de áudio, um overlay com alfa, três FCPXML
**separados** (um erro de importação aponta o recurso culpado, em vez de derrubar tudo), EDL de marcadores
coloridos, SRT e uma LUT. Os tempos são sempre múltiplos de 1/60 s.

⚠️ O vocabulário do FCPXML (versão 1.9, `asset src=`), os UIDs dos efeitos de título e de transição e a
sintaxe do EDL de marcadores do Resolve vêm de memória: o objetivo do kit é justamente descobrir o que o
Resolve gratuito aceita. Nada aqui foi validado contra o Resolve; o kit é o instrumento dessa validação.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from cronista.config import Settings
from cronista.ingest.ffmpeg import run_ffmpeg

FPS = 60
TONES = (440, 660, 880)  # faixa 1 (mix), 2 (jogo), 3 (microfone): tons diferentes para ouvir o mapeamento
CLIP_S = 20
VERSION = "1.9"


def _t(frames: int) -> str:
    return f"{frames}/{FPS}s"


def make_media(settings: Settings, out: Path) -> dict[str, Path]:
    """Clipes e overlay (FFmpeg). O HEVC fica fora se o FFmpeg não tiver `libx265`."""
    media = out / "clips"
    media.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}

    def video(name: str, source: str, codec_args: list[str], audio: tuple[int, ...], seconds: int) -> Path:
        path = media / name
        args = ["-f", "lavfi", "-i", f"{source}=size=1920x1080:rate={FPS}:duration={seconds}"]
        for tone in audio:
            args += ["-f", "lavfi", "-i", f"sine=frequency={tone}:duration={seconds}"]
        args += ["-map", "0:v", *[a for i in range(len(audio)) for a in ("-map", f"{i + 1}:a")]]
        run_ffmpeg(settings, [*args, "-r", str(FPS), *codec_args, "-c:a", "aac", str(path)])
        return path

    h264 = ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    files["A_h264"] = video("A_h264.mp4", "testsrc2", h264, TONES, CLIP_S)
    files["B_h264"] = video("B_h264.mp4", "smptebars", h264, TONES[:1], CLIP_S)
    hevc = ["-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-tag:v", "hvc1"]
    try:
        files["C_hevc"] = video("C_hevc.mp4", "testsrc2", hevc, TONES[:1], CLIP_S)
    except Exception:
        files.pop("C_hevc", None)

    # Overlay com transparência (como os do Remotion): ProRes 4444 com alfa, retângulo vermelho em fundo vazio.
    overlay = media / "overlay_alfa.mov"
    source = (
        f"color=c=black@0.0:s=1920x1080:r={FPS}:d=5,format=yuva444p10le,"
        "drawbox=x=100:y=100:w=500:h=200:color=red@0.8:t=fill"
    )
    run_ffmpeg(
        settings,
        ["-f", "lavfi", "-i", source, "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
         str(overlay)],
    )  # fmt: skip
    files["overlay_alfa"] = overlay
    return files


def _uri(path: Path) -> str:
    return path.resolve().as_uri()


def _resources(files: dict[str, Path], names: list[str]) -> str:
    rows = [
        '    <format id="r1" name="FFVideoFormat1080p60" frameDuration="1/60s" width="1920" height="1080"/>'
    ]
    for index, name in enumerate(names, start=2):
        frames = (5 if name == "overlay_alfa" else CLIP_S) * FPS
        audio = 0 if name == "overlay_alfa" else 1
        rows.append(
            f'    <asset id="r{index}" name="{name}" start="0s" duration="{_t(frames)}" hasVideo="1" '
            f'format="r1" hasAudio="{audio}" audioSources="{audio}" audioChannels="{2 * audio}" audioRate="48000" '
            f'src="{escape(_uri(files[name]))}"/>'
        )
    return "\n".join(rows)


def _wrap(name: str, resources: str, spine: str, total_frames: int, extra_resources: str = "") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>

<fcpxml version="{VERSION}">
  <resources>
{resources}
{extra_resources}  </resources>
  <library>
    <event name="Cronista kit">
      <project name="{name}">
        <sequence format="r1" duration="{_t(total_frames)}" tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k">
          <spine>
{spine}
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
"""


def fcpxml_basico(files: dict[str, Path]) -> str:
    """Corte, ordem, volume, marcador e relink: o mínimo que o app exporta hoje."""
    resources = _resources(files, ["A_h264", "B_h264"])
    spine = f"""            <asset-clip ref="r2" name="01-corte" offset="0s" start="0s" duration="{_t(300)}" format="r1" tcFormat="NDF">
              <adjust-volume amount="-6dB"/>
              <marker start="{_t(120)}" duration="{_t(1)}" value="Momento" note="momento|teste-001"/>
              <chapter-marker start="{_t(0)}" duration="{_t(1)}" value="Novo dia"/>
            </asset-clip>
            <asset-clip ref="r3" name="02-outra-fonte" offset="{_t(300)}" start="{_t(60)}" duration="{_t(300)}" format="r1" tcFormat="NDF"/>"""
    return _wrap("01-basico", resources, spine, 600)


def fcpxml_recursos(files: dict[str, Path]) -> str:
    """Velocidade constante, zoom/posição com keyframe, transição, título (cartela) e overlay com alfa."""
    names = ["A_h264", "B_h264", "overlay_alfa"] + (["C_hevc"] if "C_hevc" in files else [])
    resources = _resources(files, names)
    last = len(names) + 1
    extra = (
        f'    <effect id="r{last + 1}" name="Cross Dissolve" '
        'uid="FxPlug:4731E73A-8DAC-4113-9A30-AE85B1761265"/>\n'
        f'    <effect id="r{last + 2}" name="Basic Title" '
        'uid=".../Titles.localized/Bumper:Opener.localized/Basic Title.localized/Basic Title.moti"/>\n'
    )
    fourth = "r5" if "C_hevc" in files else "r2"
    spine = f"""            <asset-clip ref="r2" name="01-titulo-dia" offset="0s" start="0s" duration="{_t(300)}" format="r1" tcFormat="NDF">
              <title ref="r{last + 2}" lane="1" name="Dia 1" offset="0s" start="0s" duration="{_t(120)}">
                <text><text-style ref="ts1">Dia 1</text-style></text>
                <text-style-def id="ts1"><text-style font="Helvetica" fontSize="120" fontColor="1 1 1 1"/></text-style-def>
              </title>
            </asset-clip>
            <asset-clip ref="r3" name="02-velocidade-2x" offset="{_t(300)}" start="0s" duration="{_t(300)}" format="r1" tcFormat="NDF">
              <timeMap>
                <timept time="0s" value="0s" interp="linear"/>
                <timept time="{_t(300)}" value="{_t(600)}" interp="linear"/>
              </timeMap>
            </asset-clip>
            <asset-clip ref="r2" name="03-zoom-keyframes" offset="{_t(600)}" start="{_t(300)}" duration="{_t(300)}" format="r1" tcFormat="NDF">
              <adjust-transform>
                <param name="scale"><keyframeAnimation>
                  <keyframe time="{_t(300)}" value="1 1"/>
                  <keyframe time="{_t(600)}" value="1.5 1.5"/>
                </keyframeAnimation></param>
                <param name="position"><keyframeAnimation>
                  <keyframe time="{_t(300)}" value="0 0"/>
                  <keyframe time="{_t(600)}" value="10 5"/>
                </keyframeAnimation></param>
              </adjust-transform>
              <asset-clip ref="r4" lane="2" name="overlay-alfa" offset="{_t(300)}" start="0s" duration="{_t(300)}" format="r1"/>
            </asset-clip>
            <transition name="Cross Dissolve" offset="{_t(870)}" duration="{_t(60)}">
              <filter-video ref="r{last + 1}" name="Cross Dissolve"/>
            </transition>
            <asset-clip ref="{fourth}" name="04-pos-transicao{"-hevc" if fourth == "r5" else ""}" offset="{_t(900)}" start="{_t(30)}" duration="{_t(300)}" format="r1" tcFormat="NDF"/>"""
    return _wrap("02-recursos", resources, spine, 1200, extra)


def fcpxml_audio(files: dict[str, Path]) -> str:
    """Faixas de áudio do MP4 (A1 = jogo, A2 = microfone) e canais desativados (A6/A7, plano 6.3)."""
    resources = _resources(files, ["A_h264"])
    spine = f"""            <asset-clip ref="r2" name="01-faixas" offset="0s" start="0s" duration="{_t(600)}" format="r1" tcFormat="NDF">
              <audio-channel-source srcCh="1, 2" role="dialogue.jogo"/>
              <audio-channel-source srcCh="3, 4" role="dialogue.microfone"/>
              <audio-channel-source srcCh="5, 6" role="dialogue.mix-desativado" enabled="0"/>
            </asset-clip>"""
    return _wrap("03-audio", resources, spine, 600)


def marker_edl() -> str:
    """EDL de marcadores no formato do Resolve (importar na linha do tempo; cor, nome e duração)."""
    colors = [
        ("ResolveColorBlue", "Momento"),
        ("ResolveColorRed", "Morte"),
        ("ResolveColorGreen", "Conquista"),
    ]
    lines = ["TITLE: Cronista marcadores", "FCM: NON-DROP FRAME", ""]
    for n, (color, name) in enumerate(colors, start=1):
        seconds = 2 * n
        tc = f"00:00:{seconds:02d}:00"
        tc_end = f"00:00:{seconds:02d}:01"
        lines.append(f"{n:03d}  001      V     C        {tc} {tc_end} {tc} {tc_end}  ")
        lines.append(f" |C:{color} |M:{name} |D:1")
        lines.append("")
    return "\n".join(lines)


def srt() -> str:
    cues = [(1, 2, "Primeira fala do roteiro."), (4, 6, "Segunda fala, com duas linhas\nno mesmo bloco."),
            (8, 9, "Terceira.")]  # fmt: skip
    out = []
    for n, (start, end, text) in enumerate(cues, start=1):
        out.append(f"{n}\n00:00:{start:02d},000 --> 00:00:{end:02d},000\n{text}\n")
    return "\n".join(out)


def lut_cube() -> str:
    """LUT 3D 17 pontos que só aquece a imagem: o efeito é visível, o formato é o mais comum (`.cube`)."""
    size = 17
    rows = ['TITLE "Cronista teste"', f"LUT_3D_SIZE {size}"]
    for b in range(size):
        for g in range(size):
            for r in range(size):
                rr, gg, bb = r / (size - 1), g / (size - 1), b / (size - 1)
                rows.append(f"{min(1.0, rr * 1.15):.6f} {gg:.6f} {bb * 0.85:.6f}")
    return "\n".join(rows) + "\n"


def make_resolve_kit(settings: Settings, out: Path, with_media: bool = True) -> dict[str, Path]:
    """Grava o kit em `out` e devolve nome → caminho. `with_media=False` só gera os textos (testes rápidos)."""
    out.mkdir(parents=True, exist_ok=True)
    files = make_media(settings, out) if with_media else _placeholder_files(out)
    written = dict(files)
    for name, content in {
        "01-basico.fcpxml": fcpxml_basico(files),
        "02-recursos.fcpxml": fcpxml_recursos(files),
        "03-audio.fcpxml": fcpxml_audio(files),
        "marcadores.edl": marker_edl(),
        "roteiro.srt": srt(),
        "teste.cube": lut_cube(),
    }.items():
        path = out / name
        path.write_text(content, encoding="utf-8", newline="\n")
        written[name] = path
    return written


def _placeholder_files(out: Path) -> dict[str, Path]:
    media = out / "clips"
    return {n: media / f"{n}.mp4" for n in ("A_h264", "B_h264", "C_hevc")} | {
        "overlay_alfa": media / "overlay_alfa.mov"
    }

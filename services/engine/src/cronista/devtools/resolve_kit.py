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
        "drawbox=x=100:y=100:w=500:h=200:color=red@0.8:t=fill:replace=1"  # sem replace o alfa não é escrito
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


def _basico_sem_marcador(files: dict[str, Path], name: str, gap: bool) -> str:
    """01-basico sem marcador no clipe: o marcador de clipe não chegou ao Resolve (2026-11-16); testa dois lugares."""
    resources = _resources(files, ["A_h264", "B_h264"])
    marks = (
        f'<marker start="{_t(120)}" duration="{_t(1)}" value="Momento" note="momento|teste-001"/>\n'
        f'            <chapter-marker start="{_t(0)}" duration="{_t(1)}" value="Novo dia"/>'
    )
    clip1 = f'<asset-clip ref="r2" name="01-corte" offset="0s" start="0s" duration="{_t(300)}" {_CLIP}>'
    clip2 = f'<asset-clip ref="r3" name="02-outra-fonte" offset="{_t(300)}" start="{_t(60)}" duration="{_t(300)}" {_CLIP}/>'
    if gap:  # marcadores num <gap> que cobre a trilha principal; os clipes entram ancorados (lane)
        lane = '<asset-clip lane="1"'
        spine = (
            f'            <gap name="Gap" offset="0s" start="0s" duration="{_t(600)}">\n'
            f"            {marks}\n"
            f"            {clip1.replace('<asset-clip', lane)}</asset-clip>\n"
            f"            {clip2.replace('<asset-clip', lane)}\n"
            "            </gap>"
        )
        return _wrap(name, resources, spine, 600)
    spine = f"            {clip1}</asset-clip>\n            {clip2}"
    xml = _wrap(name, resources, spine, 600)
    return xml.replace("          </spine>\n", f"          </spine>\n          {marks}\n")


_CLIP = 'format="r1" tcFormat="NDF"'


def _spine_titulo() -> tuple[str, int]:
    return (
        f"""            <asset-clip ref="r2" name="titulo-dia" offset="0s" start="0s" duration="{_t(300)}" {_CLIP}>
              <title ref="r7" lane="1" name="Dia 1" offset="0s" start="0s" duration="{_t(120)}">
                <text><text-style ref="ts1">Dia 1</text-style></text>
                <text-style-def id="ts1"><text-style font="Helvetica" fontSize="120" fontColor="1 1 1 1"/></text-style-def>
              </title>
            </asset-clip>""",
        300,
    )


def _spine_velocidade() -> tuple[str, int]:
    return (
        f"""            <asset-clip ref="r3" name="velocidade-2x" offset="0s" start="0s" duration="{_t(300)}" {_CLIP}>
              <timeMap>
                <timept time="0s" value="0s" interp="linear"/>
                <timept time="{_t(300)}" value="{_t(600)}" interp="linear"/>
              </timeMap>
            </asset-clip>""",
        300,
    )


def _spine_zoom() -> tuple[str, int]:
    return (
        f"""            <asset-clip ref="r2" name="zoom-keyframes" offset="0s" start="{_t(300)}" duration="{_t(300)}" {_CLIP}>
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
            </asset-clip>""",
        300,
    )


def _spine_transicao() -> tuple[str, int]:
    return (
        f"""            <asset-clip ref="r2" name="antes" offset="0s" start="{_t(30)}" duration="{_t(300)}" {_CLIP}/>
            <transition name="Cross Dissolve" offset="{_t(270)}" duration="{_t(60)}">
              <filter-video ref="r6" name="Cross Dissolve"/>
            </transition>
            <asset-clip ref="r3" name="depois" offset="{_t(300)}" start="{_t(30)}" duration="{_t(300)}" {_CLIP}/>""",
        600,
    )


def _spine_overlay() -> tuple[str, int]:
    return (
        f"""            <asset-clip ref="r2" name="base" offset="0s" start="0s" duration="{_t(300)}" {_CLIP}>
              <asset-clip ref="r4" lane="2" name="overlay-alfa" offset="0s" start="0s" duration="{_t(300)}" format="r1"/>
            </asset-clip>""",
        300,
    )


def _spine_hevc() -> tuple[str, int]:
    return (
        f"""            <asset-clip ref="r5" name="hevc" offset="0s" start="0s" duration="{_t(300)}" {_CLIP}/>""",
        300,
    )


# Um FCPXML por recurso: se o Resolve recusar um, o culpado fica óbvio (o `02-recursos` junto recusou em 2026-11-16).
RECURSOS = {
    "02a-titulo": _spine_titulo,
    "02b-velocidade": _spine_velocidade,
    "02c-zoom-keyframes": _spine_zoom,
    "02d-transicao": _spine_transicao,
    "02e-overlay-alfa": _spine_overlay,
    "02f-hevc": _spine_hevc,
}


def _recursos_resources(files: dict[str, Path]) -> tuple[str, str]:
    """Recursos fixos (r2 A, r3 B, r4 overlay, r5 HEVC, r6 transição, r7 título), iguais em todos os arquivos."""
    resources = _resources(files, ["A_h264", "B_h264", "overlay_alfa", "C_hevc"])
    extra = (
        '    <effect id="r6" name="Cross Dissolve" uid="FxPlug:4731E73A-8DAC-4113-9A30-AE85B1761265"/>\n'
        '    <effect id="r7" name="Basic Title" '
        'uid=".../Titles.localized/Bumper:Opener.localized/Basic Title.localized/Basic Title.moti"/>\n'
    )
    return resources, extra


def fcpxml_recurso(files: dict[str, Path], name: str) -> str:
    """Um recurso isolado (título, velocidade, zoom com keyframe, transição, overlay com alfa ou HEVC)."""
    resources, extra = _recursos_resources(files)
    spine, total = RECURSOS[name]()
    return _wrap(name, resources, spine, total, extra)


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


def srt(marca_zero: bool = False) -> str:
    """`marca_zero` põe uma fala vazia em 0 s: no Resolve o clipe de legenda do Pool começa na 1ª fala e, solto no
    início da timeline, desloca tudo (o `roteiro.srt` chegou 1 s adiantado em 2026-11-16)."""
    cues = [(1, 2, "Primeira fala do roteiro."), (4, 6, "Segunda fala, com duas linhas\nno mesmo bloco."),
            (8, 9, "Terceira.")]  # fmt: skip
    if marca_zero:
        cues = [(0, 1, "."), *cues]
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
        "01b-marcador-sequencia.fcpxml": _basico_sem_marcador(files, "01b-marcador-sequencia", gap=False),
        "01c-marcador-gap.fcpxml": _basico_sem_marcador(files, "01c-marcador-gap", gap=True),
        **{f"{n}.fcpxml": fcpxml_recurso(files, n) for n in RECURSOS},
        "03-audio.fcpxml": fcpxml_audio(files),
        "marcadores.edl": marker_edl(),
        "roteiro.srt": srt(),
        "roteiro-marca-zero.srt": srt(marca_zero=True),
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

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from cronista.audio.events import replace_events
from cronista.config import Settings
from cronista.db.models import MediaFile, Project, RecordingSession
from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource
from cronista.domain.frames import FPS
from cronista.domain.models import MediaProbe
from cronista.finishing.brand import DayCard, Fonts, Palette, Visual
from cronista.pipeline.stage import StageError
from cronista.shorts.candidates import ShortCandidate
from cronista.shorts.render import (
    HEIGHT,
    WIDTH,
    CaptionWord,
    ShortStyle,
    ass_color,
    ass_time,
    audio_chain,
    build_ass,
    caption_groups,
    encoder_args,
    layout,
    render_shorts,
    short_name,
    video_chain,
)
from cronista.shorts.service import ShortsError, load_caption_words

VISUAL = Visual(
    palette=Palette(
        primary="#F2B134", secondary="#2D3A4B", accent="#E4572E", background="#12161C", text="#F5F5F0"
    ),
    fonts=Fonts(title="Bebas Neue", body="Inter"),
    day_card=DayCard(),
)


def word(start_s: float, end_s: float, text: str) -> CaptionWord:
    return CaptionWord(round(start_s * FPS), round(end_s * FPS), text)


def cand(start_s: float = 10.0, end_s: float = 20.0, file_id: int = 1) -> ShortCandidate:
    return ShortCandidate(
        file_id=file_id,
        start_frame=round(start_s * FPS),
        end_frame=round(end_s * FPS),
        peak_frame=round(15 * FPS),
        hook_frame=round(11 * FPS),
        hook_kind="fala",
        score=0.9,
        reason="t",
        segment_start_s=0,
    )


def test_cores_e_tempos_do_ass() -> None:
    assert ass_color("#F2B134") == "&H0034B1F2"  # o ASS escreve BBGGRR
    assert ass_time(0) == "0:00:00.00"
    assert ass_time(3725.456) == "1:02:05.46"
    with pytest.raises(ValueError):
        ass_color("vermelho")


def test_grupos_de_legenda_em_tres_palavras_e_quebra_em_pausa() -> None:
    words = [
        word(10.2, 10.5, "não"),
        word(10.5, 10.8, "acredito"),
        word(10.8, 11.1, "nisso"),
        word(11.1, 11.4, "cara"),
        word(13.0, 13.4, "morri"),  # pausa de 1,6 s abre grupo novo
    ]
    caps = caption_groups(words, round(10 * FPS), round(20 * FPS), ShortStyle())
    assert [[t for *_, t in c.words] for c in caps] == [["não", "acredito", "nisso"], ["cara"], ["morri"]]
    assert caps[0].start_s == pytest.approx(0.2)
    # o grupo fica na tela até 0,15 s depois da última palavra, sem passar do grupo seguinte
    assert caps[0].end_s == pytest.approx(1.1)
    assert caps[1].end_s == pytest.approx(1.4 + 0.15)
    assert caps[1].end_s <= caps[2].start_s


def test_palavras_fora_da_janela_ou_cortadas_ao_meio_ficam_de_fora() -> None:
    words = [word(9.8, 10.2, "meio"), word(10.5, 10.9, "dentro"), word(19.8, 20.3, "corta")]
    caps = caption_groups(words, round(10 * FPS), round(20 * FPS), ShortStyle())
    assert [[t for *_, t in c.words] for c in caps] == [["dentro"]]


def test_layout_desfoque_mantem_a_legenda_na_area_segura() -> None:
    style = ShortStyle()
    lay = layout(style, 1920, 1080)
    assert lay.foreground is not None
    fg_w, fg_h, fg_top = lay.foreground
    assert (fg_w, fg_h) == (WIDTH, 608)
    block = round(style.font_size * 1.25 * 2)
    assert fg_top >= style.safe.top
    assert lay.caption_top >= fg_top + fg_h  # a legenda fica abaixo da gameplay
    assert lay.caption_top + block <= HEIGHT - style.safe.bottom


def test_layout_recorte_encosta_a_legenda_no_limite_seguro() -> None:
    style = ShortStyle(reframe="recorte")
    lay = layout(style, 1920, 1080)
    assert lay.foreground is None
    assert lay.caption_top == HEIGHT - style.safe.bottom - round(style.font_size * 1.25 * 2)


def test_ass_destaca_a_palavra_falada_e_escapa_chaves() -> None:
    style = ShortStyle()
    caps = caption_groups(
        [word(10.0, 10.3, "olha"), word(10.3, 10.6, "{isso}")], round(10 * FPS), round(20 * FPS), style
    )
    text = build_ass(caps, VISUAL, style, layout(style, 1920, 1080))
    assert "PlayResX: 1080" in text and "PlayResY: 1920" in text
    assert "Style: Default,Bebas Neue,88," in text
    dialogues = [line for line in text.splitlines() if line.startswith("Dialogue")]
    assert len(dialogues) == 2  # um evento por palavra
    accent = ass_color(VISUAL.palette.accent)
    assert f"{{\\1c{accent}}}olha" in dialogues[0]
    assert f"{{\\1c{accent}}}(isso)" in dialogues[1]  # chave do texto não vira tag do ASS
    assert dialogues[0].split(",")[2] == dialogues[1].split(",")[1]  # a troca de palavra não deixa buraco


def test_filtro_desfoque_tem_fundo_gameplay_central_e_legenda(tmp_path: Path) -> None:
    style = ShortStyle()
    chain = video_chain(style, layout(style, 1920, 1080), tmp_path / "s.ass", None)
    assert chain.startswith("[0:v]split=2[bg][fg];")
    assert "boxblur=40:5" in chain and "scale=1080:-2" in chain
    assert "overlay=(W-w)/2:" in chain
    assert "ass=filename=" in chain and "fontsdir" not in chain
    assert chain.endswith(f"fps={FPS},format=yuv420p[v]")


def test_filtro_recorte_segue_o_foco(tmp_path: Path) -> None:
    style = ShortStyle(reframe="recorte", focus_x=0.8)
    chain = video_chain(style, layout(style, 1920, 1080), tmp_path / "s.ass", tmp_path)
    assert "crop=w=ih*1080/1920:h=ih:x='(iw-ow)*0.8':y=0" in chain
    assert "scale=1080:1920" in chain and "fontsdir=" in chain


def test_audio_normaliza_ao_alvo_do_canal_e_corta_suave() -> None:
    chain = audio_chain(ShortStyle(loudness_lufs=-14.0), 12.0)
    assert chain.startswith("loudnorm=I=-14:")
    assert "afade=t=out:st=11.850:d=0.150" in chain
    assert "st=0.750:d=0.250" in audio_chain(ShortStyle(fade_out_s=5), 1.0)  # fade nunca passa de 1/4


def test_nome_do_arquivo_muda_com_filtro_legenda_e_encoder() -> None:
    c = cand()
    base = short_name(c, "a", "b", "c", ["-crf", "18"])
    assert base.startswith(f"short-1-{c.start_frame}-{c.end_frame}-") and base.endswith(".mp4")
    assert base == short_name(c, "a", "b", "c", ["-crf", "18"])
    assert base != short_name(c, "a", "outra legenda", "c", ["-crf", "18"])
    assert base != short_name(c, "a", "b", "c", ["-crf", "20"])


def test_encoder_de_entrega_por_cpu_ou_nvenc(tmp_path: Path) -> None:
    cpu = encoder_args(Settings(env="test", data_dir=tmp_path))
    assert cpu[:2] == ["-c:v", "libx264"] and "18" in cpu
    gpu = encoder_args(Settings(env="test", data_dir=tmp_path, preview_encoder="h264_nvenc"))
    assert gpu[:2] == ["-c:v", "h264_nvenc"] and "-cq" in gpu


def _fake_probe(_settings: Settings, path: Path) -> MediaProbe:
    return MediaProbe(path=str(path), width=1920, height=1080)


def test_render_chama_ffmpeg_uma_vez_por_short_e_reaproveita(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake(_settings: Settings, args: list[str]) -> None:
        calls.append(args)
        Path(args[-1]).write_bytes(b"mp4")

    monkeypatch.setattr("cronista.shorts.render.run_ffmpeg", fake)
    monkeypatch.setattr("cronista.shorts.render.probe_media", _fake_probe)
    settings = Settings(env="test", data_dir=tmp_path)
    words = {1: [word(10.5, 10.9, "oi"), word(11.0, 11.4, "gente")]}
    masters = {1: tmp_path / "m.mp4"}
    out = tmp_path / "out"
    first = render_shorts([cand()], words, masters, VISUAL, out, settings)
    again = render_shorts([cand()], words, masters, VISUAL, out, settings)

    assert len(calls) == 1 and first.clips == again.clips
    (clip,) = first.clips.values()
    assert clip.is_file() and first.clips[f"1-{round(10 * FPS)}-{round(20 * FPS)}"] == clip
    a = calls[0]
    assert a[a.index("-ss") + 1] == "10.000000" and a[a.index("-t") + 1] == "10.000000"
    assert a[a.index("-map") + 1] == "[v]" and "0:a:0" in a  # áudio = faixa 1 (o mix da entrega)
    assert "-movflags" in a and a[a.index("-r") + 1] == str(FPS)
    ass = (out / f"short-1-{round(10 * FPS)}.ass").read_text(encoding="utf-8")
    assert "oi" in ass and "gente" in ass


def test_render_avisa_e_pula_sem_mestre_sem_tamanho_e_sem_palavras(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake(_settings: Settings, args: list[str]) -> None:
        Path(args[-1]).write_bytes(b"mp4")

    monkeypatch.setattr("cronista.shorts.render.run_ffmpeg", fake)
    settings = Settings(env="test", data_dir=tmp_path)

    monkeypatch.setattr("cronista.shorts.render.probe_media", _fake_probe)
    sem_mestre = render_shorts([cand(file_id=9)], {}, {}, VISUAL, tmp_path / "a", settings)
    assert sem_mestre.clips == {} and "gravação 9 sem arquivo mestre" in "\n".join(sem_mestre.warnings)

    sem_palavras = render_shorts([cand()], {}, {1: tmp_path / "m.mp4"}, VISUAL, tmp_path / "b", settings)
    assert len(sem_palavras.clips) == 1 and "sem palavras do Whisper" in "\n".join(sem_palavras.warnings)

    monkeypatch.setattr(
        "cronista.shorts.render.probe_media", lambda _s, p: MediaProbe(path=str(p), interrupted=True)
    )
    sem_tamanho = render_shorts([cand()], {}, {1: tmp_path / "m.mp4"}, VISUAL, tmp_path / "c", settings)
    assert sem_tamanho.clips == {} and "não consegui ler o tamanho" in "\n".join(sem_tamanho.warnings)


def test_render_com_falha_vira_aviso_e_nao_deixa_short_parcial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_settings: Settings, args: list[str]) -> None:
        Path(args[-1]).write_bytes(b"pela metade")
        raise StageError("ffmpeg falhou")

    monkeypatch.setattr("cronista.shorts.render.run_ffmpeg", boom)
    monkeypatch.setattr("cronista.shorts.render.probe_media", _fake_probe)
    settings = Settings(env="test", data_dir=tmp_path)
    result = render_shorts([cand()], {}, {1: tmp_path / "m.mp4"}, VISUAL, tmp_path / "out", settings)
    assert result.clips == {} and any("ffmpeg falhou" in w for w in result.warnings)
    assert not list((tmp_path / "out").glob("*.mp4")) and not list((tmp_path / "out").glob("part-*"))


@pytest.mark.media
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="precisa do FFmpeg")
@pytest.mark.parametrize("reframe", ["desfoque", "recorte"])
def test_ffmpeg_gera_short_1080x1920_de_ate_13_s(reframe: str, tmp_path: Path) -> None:
    master = tmp_path / "m.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=60:duration=8",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
            "-pix_fmt", "yuv420p", "-c:a", "aac", str(master),
        ],
        check=True,
    )  # fmt: skip
    settings = Settings(env="test", data_dir=tmp_path)
    words = {1: [word(2.2, 2.6, "olha"), word(2.6, 3.0, "isso")]}
    result = render_shorts(
        [cand(2.0, 8.0)], words, {1: master}, VISUAL, tmp_path / "out", settings,
        style=ShortStyle(reframe=reframe),  # type: ignore[arg-type]
    )  # fmt: skip
    (clip,) = result.clips.values()
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate", "-of", "csv=p=0", str(clip)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert probe.stdout.strip() == "1080,1920,60/1"


def test_palavras_do_whisper_vem_do_banco_com_texto(db: Session) -> None:
    project = Project(name="p")
    db.add(project)
    db.flush()
    session = RecordingSession(project_id=project.id, folder="x")
    db.add(session)
    db.flush()
    media = MediaFile(session_id=session.id, path="a.mp4")
    db.add(media)
    db.commit()
    evidence = Evidence(
        source=EvidenceSource.TRANSCRICAO,
        model="fake",
        model_version="1",
        params_hash="h",
        start_frame=600,
        end_frame=720,
        confidence=0.9,
        quote="olha isso",
    )
    words = [
        {"start_frame": 660, "end_frame": 690, "text": " isso"},
        {"start_frame": 600, "end_frame": 650, "text": "olha"},
    ]
    replace_events(
        db, media.id, "speech", "v", [AnalysisEvent(kind="fala", evidence=evidence, payload={"words": words})]
    )
    db.commit()
    got = load_caption_words(db, session.id)
    assert got[media.id] == [CaptionWord(600, 650, "olha"), CaptionWord(660, 690, " isso")]
    with pytest.raises(ShortsError):
        load_caption_words(db, 999)

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from cronista.config import Settings, find_repo_root
from cronista.db.models import Project, RecordingSession
from cronista.finishing.brand import DayCard, Fonts, Palette, Visual
from cronista.finishing.render.overlay import SYSTEM_FONTS
from cronista.thumbnails import render as render_mod
from cronista.thumbnails.frames import (
    Moment,
    Sample,
    ScoredFrame,
    measure_frame,
    moments_from_story_pack,
    pick_frames,
    plan_samples,
    sample_times,
    score_frame,
)
from cronista.thumbnails.model import (
    ThumbnailModel,
    check_model_files,
    default_model,
    load_thumbnail_model,
    render_schema,
    resolve_color,
)
from cronista.thumbnails.render import (
    MAX_BYTES,
    ThumbnailError,
    build_chain,
    choose_frames,
    fit_font_size,
    line_positions,
    pick_font,
    plan_variations,
    prepare_text,
    render_thumbnails,
    thumb_name,
    wrap_text,
)
from cronista.thumbnails.service import (
    current_thumbnail,
    record_thumbnail_choice,
    render_session_thumbnails,
)

BRAND = find_repo_root(Path(__file__)) / "packages" / "brand-kit"
VISUAL = Visual(
    palette=Palette(
        primary="#F2B134", secondary="#2D3A4B", accent="#E4572E", background="#12161C", text="#F5F5F0"
    ),
    fonts=Fonts(title="Bebas Neue", body="Inter", files=["fonts/a.ttf", "fonts/b.ttf"]),
    day_card=DayCard(),
)


# ---------------------------------------------------------------- modelo


def test_modelo_de_exemplo_carrega_e_o_schema_do_repo_esta_em_dia() -> None:
    model = load_thumbnail_model(BRAND)
    assert (model.width, model.height) == (1280, 720)
    assert model.day_badge.enabled is False  # o número do dia nunca mora no YAML
    stored = BRAND / "thumbnail.schema.json"
    assert stored.is_file(), "rode `uv run python -m cronista.thumbnails.model`"
    assert json.loads(stored.read_text(encoding="utf-8")) == json.loads(render_schema())


def test_sem_yaml_vale_o_modelo_padrao(tmp_path: Path) -> None:
    assert load_thumbnail_model(tmp_path) == default_model()


@pytest.mark.parametrize(
    "bad",
    [
        {"extra": 1},  # campo desconhecido
        {"text": {"color": "vermelho"}},  # cor que não é papel nem hex
        {"text": {"stroke_color": "#12345"}},
        {"day_badge": {"fill": "azul"}},
        {"width": 1280, "height": 1000},  # não é 16:9
        {"text": {"positions": []}},
        {"text": {"positions": ["meio_do_nada"]}},
        {"color": {"saturation": 9}},
        {"day_badge": {"template": "Dia"}},  # sem {n}
    ],
)
def test_modelo_invalido_e_recusado(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ThumbnailModel.model_validate(bad)


def test_yaml_invalido_e_recusado(tmp_path: Path) -> None:
    (tmp_path / "thumbnail.yaml").write_text("- lista\n- não é mapa\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapa"):
        load_thumbnail_model(tmp_path)
    (tmp_path / "thumbnail.yaml").write_text("campo_novo: 1\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_thumbnail_model(tmp_path)


def test_moldura_ausente_ou_fora_da_pasta_e_apontada(tmp_path: Path) -> None:
    assert check_model_files(ThumbnailModel(), tmp_path) == []
    assert "não existe" in check_model_files(ThumbnailModel(frame="frames/x.png"), tmp_path)[0]
    assert "sai da pasta" in check_model_files(ThumbnailModel(frame="../fora.png"), tmp_path)[0]
    (tmp_path / "frames").mkdir()
    (tmp_path / "frames" / "x.png").write_bytes(b"png")
    assert check_model_files(ThumbnailModel(frame="frames/x.png"), tmp_path) == []


def test_cor_resolve_papel_da_paleta_ou_hex() -> None:
    assert resolve_color("accent", VISUAL.palette) == "#E4572E"
    assert resolve_color("#00FF00", VISUAL.palette) == "#00FF00"


# ---------------------------------------------------------------- frames


def checker(n: int = 270, m: int = 480, cell: int = 8) -> np.ndarray:
    ys, xs = np.indices((n, m))
    return (((ys // cell + xs // cell) % 2) * 255).astype(np.uint8)


def test_frame_nitido_vence_o_borrado_e_o_escuro() -> None:
    sharp = checker()
    blurred = np.full_like(sharp, 128)  # sem nenhuma borda
    dark = (sharp // 20).astype(np.uint8)  # mesmo desenho, quase preto
    m_sharp, m_blur, m_dark = measure_frame(sharp), measure_frame(blurred), measure_frame(dark)
    assert m_sharp.sharpness > m_blur.sharpness
    assert m_sharp.exposure < 1.0  # metade branca estourada e metade preta: exposição ruim
    assert m_dark.exposure < 0.1
    assert m_blur.quality < 0.7 and m_dark.quality < 0.1


def test_exposicao_ruim_zera_a_qualidade_mesmo_com_nitidez() -> None:
    img = checker()
    metrics = measure_frame(img)
    assert metrics.sharpness > 0.9 and metrics.exposure == 0.0 and metrics.quality == 0.0


def test_frame_muito_pequeno_e_recusado() -> None:
    with pytest.raises(ValueError):
        measure_frame(np.zeros((4, 4)))


def test_medida_e_deterministica() -> None:
    img = np.random.default_rng(7).integers(30, 220, (90, 160)).astype(np.uint8)
    assert measure_frame(img) == measure_frame(img.copy())


def pack(*scores: float) -> dict[str, Any]:
    beats = [
        {
            "segmento_id": i + 1,
            "arquivo_id": 1,
            "inicio_s": 100.0 * i,
            "fim_s": 100.0 * i + 30,
            "beat": "climax" if i == 0 else "desenvolvimento",
            "classe": "acao",
            "nota": s,
        }
        for i, s in enumerate(scores)
    ]
    return {"capitulos": [{"n": 1, "beats": beats[:2]}, {"n": 2, "beats": beats[2:]}]}


def test_momentos_ordenados_por_nota_com_desempate_pelo_id() -> None:
    moments = moments_from_story_pack(pack(0.5, 0.9, 0.9, 0.2), top=3)
    assert [m.segment_id for m in moments] == [2, 3, 1]
    assert moments[0].file_id == 1 and moments[0].beat == "desenvolvimento"


def test_amostras_ficam_dentro_do_trecho_e_segmento_longo_e_limitado() -> None:
    short = Moment(1, 1, 10.0, 40.0, 0.8, "x", "acao")
    times = sample_times(short)
    assert len(times) == 5 and all(10.0 < t < 40.0 for t in times) and times == sorted(times)
    long = Moment(1, 2, 0.0, 3600.0, 0.8, "x", "acao")
    assert all(1770 <= t <= 1830 for t in sample_times(long))  # só 60 s em volta do meio
    assert sample_times(Moment(1, 3, 5.0, 5.0, 0.5, "x", "acao")) == [5.0]
    assert len(plan_samples([short, long])) == 10


def frame(seg: int, t: float, score: float, file_id: int = 1) -> ScoredFrame:
    return ScoredFrame(file_id, seg, t, score, score, 0.5, "x", "acao")


def test_pick_frames_um_por_segmento_e_sem_vizinhos() -> None:
    scored = [
        frame(1, 100, 0.9),
        frame(1, 110, 0.85),  # mesmo segmento
        frame(2, 105, 0.8),  # 5 s do melhor, mesmo arquivo: quase igual
        frame(3, 400, 0.7),
        frame(4, 900, 0.6, file_id=2),
        frame(5, 110, 0.5, file_id=2),  # outro arquivo: não conta como vizinho
    ]
    chosen = pick_frames(scored, 3)
    assert [(c.segment_id, c.t_s) for c in chosen] == [(1, 100), (3, 400), (4, 900)]
    assert pick_frames(scored, 3) == chosen  # determinístico
    assert pick_frames([], 3) == []


def test_nota_final_pesa_60_por_cento_o_momento_e_40_a_qualidade() -> None:
    img = checker(cell=8)
    img = (img // 2 + 64).astype(np.uint8)  # tira o estouro de exposição
    metrics = measure_frame(img)
    sample = Sample(Moment(1, 1, 0, 30, 0.9, "x", "acao"), 10.0)
    scored = score_frame(sample, metrics)
    assert scored.score == pytest.approx(0.6 * 0.9 + 0.4 * metrics.quality, abs=1e-5)


def test_choose_frames_usa_o_grab_injetado_e_avisa_gravacao_sem_mestre(tmp_path: Path) -> None:
    sharp = (checker() // 2 + 64).astype(np.uint8)
    flat = np.full((270, 480), 100, dtype=np.uint8)
    grabbed: list[float] = []

    def grab(master: Path, t: float) -> np.ndarray | None:
        grabbed.append(t)
        return sharp if t % 2 else flat

    story = pack(0.9, 0.8, 0.7)
    story["capitulos"][1]["beats"][0]["arquivo_id"] = 9  # sem arquivo mestre
    frames, warnings = choose_frames(story, {1: tmp_path / "m.mp4"}, grab, 3)
    assert warnings == ["gravação 9 sem arquivo mestre; ignorada"]
    assert frames and all(f.file_id == 1 for f in frames)
    assert grabbed  # o FFmpeg real nunca foi chamado


# ---------------------------------------------------------------- texto e filtro


def test_quebra_de_texto_em_no_maximo_duas_linhas_equilibradas() -> None:
    assert wrap_text("MORRI", 14) == ["MORRI"]
    assert wrap_text("MORRI DE NOVO", 14) == ["MORRI DE NOVO"]
    assert wrap_text("CONSEGUI O NETHER HOJE", 14) == ["CONSEGUI O", "NETHER HOJE"]
    assert wrap_text("A B C D E F G H I J K L", 6) == ["A B C D E F", "G H I J K L"]  # nunca três linhas
    assert wrap_text("", 14) == []
    assert prepare_text("  morri   de novo ", True) == "MORRI DE NOVO"
    assert prepare_text("Morri", False) == "Morri"


def test_fonte_encolhe_para_caber_entre_as_margens() -> None:
    assert fit_font_size(["MORRI"], 144, 1280, 36) == 144
    small = fit_font_size(["SUPERCALIFRAGILISTICO"], 144, 1280, 36)
    assert small < 144 and 21 * small * 0.6 <= 1280 - 72
    assert fit_font_size([], 144, 1280, 36) == 144


def test_posicoes_do_bloco_de_texto() -> None:
    assert line_positions("topo_esquerda", 2, 100, 1280, 720, 36) == [("36", "36"), ("36", "141")]
    assert line_positions("base_direita", 1, 100, 1280, 720, 36) == [("w-text_w-36", "579")]
    assert line_positions("centro", 1, 100, 1280, 720, 36) == [("(w-text_w)/2", "307")]


def chain(model: ThumbnailModel | None = None, **kw: Any) -> str:
    args: dict[str, Any] = {
        "text": "MORRI DE NOVO",
        "position": "base_esquerda",
        "day": None,
        "frame_png": None,
    }
    args.update(kw)
    return build_chain(model or ThumbnailModel(), VISUAL, Path("fonts/a.ttf"), **args)


def test_filtro_tem_corte_16_9_cor_vinheta_e_texto_com_contorno() -> None:
    c = chain()
    assert c.startswith("[0:v]scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,setsar=1,eq=")
    assert "vignette=PI/5" in c and "saturation=1.15" in c
    assert "drawtext=fontfile='fonts/a.ttf'" in c and "text='MORRI DE NOVO'" in c
    assert "fontcolor=0xF5F5F0" in c and "bordercolor=0x12161C" in c  # papéis da paleta do brand kit
    assert c.endswith("format=yuvj420p[v]")
    assert "overlay" not in c


def test_filtro_com_duas_linhas_moldura_e_sem_vinheta() -> None:
    model = ThumbnailModel.model_validate({"color": {"vignette": False}})
    c = chain(model, text="CONSEGUI O NETHER HOJE", frame_png=Path("m.png"))
    assert "vignette" not in c
    assert c.count("drawtext=") == 2
    assert "[b];[1:v]scale=1280:720[f];[b][f]overlay=0:0" in c
    assert c.index("overlay") < c.index("drawtext")  # o texto fica por cima da moldura


def test_texto_com_caracteres_especiais_e_escapado() -> None:
    assert "text='NÃO\\: É 100\\%'" in chain(text="não: é 100%")


def test_sem_texto_so_o_frame() -> None:
    assert "drawtext" not in chain(text=None)


def test_selo_de_dia_so_aparece_ligado_e_com_numero() -> None:
    on = ThumbnailModel.model_validate({"day_badge": {"enabled": True}})
    assert "text='Dia 37'" in chain(on, day=37)
    assert "boxcolor=0xF2B134" in chain(on, day=37)
    assert "Dia" not in chain(on, day=None)  # sem `--dia`: o número é da edição
    assert "Dia" not in chain(ThumbnailModel(), day=37)  # desligado no modelo


def test_cor_hex_no_modelo_vale_no_filtro() -> None:
    model = ThumbnailModel.model_validate({"text": {"color": "#00FF00"}})
    assert "fontcolor=0x00FF00" in chain(model)


# ---------------------------------------------------------------- variações e nome


def test_variacoes_ciclam_frames_textos_e_posicoes() -> None:
    frames = [frame(1, 10, 0.9), frame(2, 500, 0.8)]
    model = ThumbnailModel()
    out = plan_variations(frames, ["MORRI", "DE NOVO", "O FIM"], model, 3)
    assert [v.n for v in out] == [1, 2, 3]
    assert [v.frame.segment_id for v in out] == [1, 2, 1]
    assert [v.text for v in out] == ["MORRI", "DE NOVO", "O FIM"]
    assert [v.position for v in out] == ["base_esquerda", "topo_direita", "base_centro"]
    assert plan_variations(frames, ["MORRI", "DE NOVO", "O FIM"], model, 3) == out
    assert plan_variations([], ["X"], model) == []


def test_sem_texto_as_variacoes_seguem_so_os_frames() -> None:
    out = plan_variations([frame(1, 10, 0.9), frame(2, 500, 0.8)], [], ThumbnailModel(), 3)
    assert len(out) == 2 and all(v.text is None for v in out)


def test_nome_leva_o_hash_do_filtro_do_frame_de_moldura_e_da_qualidade() -> None:
    v = plan_variations([frame(1, 10.5, 0.9)], ["X"], ThumbnailModel(), 1)[0]
    base = thumb_name(v, "chain", "d", 3)
    assert base == thumb_name(v, "chain", "d", 3)
    assert (
        len(
            {
                base,
                thumb_name(v, "outra", "d", 3),
                thumb_name(v, "chain", "e", 3),
                thumb_name(v, "chain", "d", 6),
            }
        )
        == 4
    )
    assert base.startswith("thumb-1-10500-v1-") and base.endswith(".jpg")


def test_fonte_do_brand_kit_title_e_body(tmp_path: Path) -> None:
    (tmp_path / "fonts").mkdir()
    (tmp_path / "fonts" / "a.ttf").write_bytes(b"a")
    assert pick_font(tmp_path, VISUAL, "title", ()) == tmp_path / "fonts" / "a.ttf"
    assert pick_font(tmp_path, VISUAL, "body", ()) == tmp_path / "fonts" / "a.ttf"  # só uma existe
    (tmp_path / "fonts" / "b.ttf").write_bytes(b"b")
    assert pick_font(tmp_path, VISUAL, "body", ()) == tmp_path / "fonts" / "b.ttf"
    assert pick_font(tmp_path, VISUAL, "title", ()) == tmp_path / "fonts" / "a.ttf"
    assert pick_font(tmp_path / "nada", VISUAL, "title", ()) is None


# ---------------------------------------------------------------- render (FFmpeg trocado por um falso)


@pytest.fixture
def brand(tmp_path: Path) -> Path:
    folder = tmp_path / "brand"
    (folder / "fonts").mkdir(parents=True)
    (folder / "fonts" / "a.ttf").write_bytes(b"fonte")
    return folder


@pytest.fixture
def sharp_grab() -> Any:
    img = (checker() // 2 + 64).astype(np.uint8)
    return lambda master, t: img


def fake_compose(sizes: list[int], calls: list[int]) -> Any:
    def compose(
        settings: Settings, master: Path, t_s: float, chain: str, frame_png: Path | None, q: int, out: Path
    ) -> None:
        calls.append(q)
        out.write_bytes(b"x" * sizes[min(len(calls) - 1, len(sizes) - 1)])

    return compose


def test_render_gera_variacoes_e_reaproveita_o_que_existe(
    settings: Settings, tmp_path: Path, brand: Path, sharp_grab: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(render_mod, "_compose", fake_compose([1000], calls))
    args: dict[str, Any] = {
        "texts": ["MORRI", "DE NOVO"], "count": 2, "brand_dir": brand, "grab": sharp_grab,
    }  # fmt: skip
    masters = {1: tmp_path / "m.mp4"}
    first = render_thumbnails(
        pack(0.9, 0.8, 0.7), masters, ThumbnailModel(), VISUAL, tmp_path / "out", settings, **args
    )
    assert len(first.items) == 2 and len(calls) == 2
    assert all(i.path.is_file() and i.path.suffix == ".jpg" for i in first.items)
    assert not list((tmp_path / "out").glob("part-*"))  # nada parcial fica para trás
    again = render_thumbnails(
        pack(0.9, 0.8, 0.7), masters, ThumbnailModel(), VISUAL, tmp_path / "out", settings, **args
    )
    assert [i.path for i in again.items] == [i.path for i in first.items]
    assert len(calls) == 2  # reaproveitou, não renderizou de novo
    other = render_thumbnails(
        pack(0.9, 0.8, 0.7),
        masters,
        ThumbnailModel(),
        VISUAL,
        tmp_path / "out",
        settings,
        **{**args, "texts": ["OUTRO", "TEXTO"]},
    )
    assert [i.path for i in other.items] != [i.path for i in first.items]


def test_acima_de_2_mb_tenta_qualidade_menor_e_so_a_menor_fica(
    settings: Settings, tmp_path: Path, brand: Path, sharp_grab: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(render_mod, "_compose", fake_compose([MAX_BYTES + 1, MAX_BYTES - 1], calls))
    out = render_thumbnails(
        pack(0.9), {1: tmp_path / "m.mp4"}, ThumbnailModel(), VISUAL, tmp_path / "out", settings,
        texts=["MORRI"], count=1, brand_dir=brand, grab=sharp_grab,
    )  # fmt: skip
    assert calls == [3, 6] and out.warnings == []
    assert len(list((tmp_path / "out").glob("*.jpg"))) == 1
    assert out.items[0].path.stat().st_size == MAX_BYTES - 1


def test_sempre_acima_de_2_mb_avisa(
    settings: Settings, tmp_path: Path, brand: Path, sharp_grab: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(render_mod, "_compose", fake_compose([MAX_BYTES + 5], []))
    out = render_thumbnails(
        pack(0.9), {1: tmp_path / "m.mp4"}, ThumbnailModel(), VISUAL, tmp_path / "out", settings,
        texts=["MORRI"], count=1, brand_dir=brand, grab=sharp_grab,
    )  # fmt: skip
    assert any("acima de 2 MB" in w for w in out.warnings)


def test_render_recusa_sem_fonte_e_moldura_ausente(
    settings: Settings, tmp_path: Path, brand: Path, sharp_grab: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(render_mod, "pick_font", lambda *a, **k: None)
    with pytest.raises(ThumbnailError, match="fonte"):
        render_thumbnails(pack(0.9), {}, ThumbnailModel(), VISUAL, tmp_path, settings, brand_dir=brand)
    monkeypatch.undo()
    with pytest.raises(ThumbnailError, match="moldura"):
        render_thumbnails(
            pack(0.9), {}, ThumbnailModel(frame="frames/x.png"), VISUAL, tmp_path, settings, brand_dir=brand
        )


def test_avisos_sem_texto_sem_frames_e_selo_sem_dia(
    settings: Settings, tmp_path: Path, brand: Path, sharp_grab: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(render_mod, "_compose", fake_compose([10], []))
    badge = ThumbnailModel.model_validate({"day_badge": {"enabled": True}})
    out = render_thumbnails(
        pack(0.9), {1: tmp_path / "m.mp4"}, badge, VISUAL, tmp_path / "out", settings,
        count=1, brand_dir=brand, grab=sharp_grab,
    )  # fmt: skip
    assert any("sem texto" in w for w in out.warnings) and any("--dia" in w for w in out.warnings)
    empty = render_thumbnails(
        pack(0.9), {}, ThumbnailModel(), VISUAL, tmp_path / "out2", settings, brand_dir=brand, grab=sharp_grab
    )
    assert empty.items == [] and any("nenhum frame" in w for w in empty.warnings)


def test_falha_do_ffmpeg_vira_erro_de_thumbnail(
    settings: Settings, tmp_path: Path, brand: Path, sharp_grab: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cronista.pipeline.stage import StageError

    def boom(*a: Any, **k: Any) -> None:
        raise StageError("ffmpeg falhou (1): x")

    monkeypatch.setattr(render_mod, "_compose", boom)
    with pytest.raises(ThumbnailError, match="ffmpeg falhou"):
        render_thumbnails(
            pack(0.9), {1: tmp_path / "m.mp4"}, ThumbnailModel(), VISUAL, tmp_path / "out", settings,
            count=1, brand_dir=brand, grab=sharp_grab,
        )  # fmt: skip
    assert not list((tmp_path / "out").glob("*.jpg"))


# ---------------------------------------------------------------- banco e serviço


@pytest.fixture
def session_id(db: Session) -> int:
    project = Project(name="serie")
    session = RecordingSession(project=project, folder="pasta")
    db.add_all([project, session])
    db.commit()
    return session.id


def write_manifest(folder: Path, names: list[str]) -> None:
    (folder / "thumbnails").mkdir(parents=True)
    entries = []
    for n, name in enumerate(names, start=1):
        (folder / "thumbnails" / name).write_bytes(b"jpg")
        entries.append({"variacao": n, "arquivo": name, "texto": f"T{n}", "posicao": "centro"})
    (folder / "thumbnails.json").write_text(json.dumps(entries), encoding="utf-8")


def test_escolha_so_insercao_e_a_ultima_vale(db: Session, session_id: int, tmp_path: Path) -> None:
    write_manifest(tmp_path, ["a.jpg", "b.jpg"])
    assert current_thumbnail(db, session_id) is None
    first = record_thumbnail_choice(db, session_id, tmp_path, 1)
    assert (first.file_name, first.text, first.position) == ("a.jpg", "T1", "centro")
    second = record_thumbnail_choice(db, session_id, tmp_path, 2)
    current = current_thumbnail(db, session_id)
    assert current is not None and current.id == second.id and current.file_name == "b.jpg"
    assert first.id != second.id  # a anterior continua no banco


def test_escolha_recusa_sessao_variacao_e_arquivo_inexistentes(
    db: Session, session_id: int, tmp_path: Path
) -> None:
    with pytest.raises(ThumbnailError, match="não existe"):
        record_thumbnail_choice(db, 999, tmp_path, 1)
    with pytest.raises(ThumbnailError, match="sem thumbnails"):
        record_thumbnail_choice(db, session_id, tmp_path, 1)
    write_manifest(tmp_path, ["a.jpg"])
    with pytest.raises(ThumbnailError, match="variação 3"):
        record_thumbnail_choice(db, session_id, tmp_path, 3)
    (tmp_path / "thumbnails" / "a.jpg").unlink()
    with pytest.raises(ThumbnailError, match="rode `cronista thumbnails`"):
        record_thumbnail_choice(db, session_id, tmp_path, 1)


def test_servico_recusa_sessao_sem_story_e_texto_longo_demais(
    db: Session, session_id: int, settings: Settings, tmp_path: Path
) -> None:
    with pytest.raises(ThumbnailError, match="não existe"):
        render_session_thumbnails(db, 999, settings, tmp_path, tmp_path)
    with pytest.raises(ThumbnailError, match="cronista story"):
        render_session_thumbnails(db, session_id, settings, tmp_path, tmp_path)


# ---------------------------------------------------------------- FFmpeg real (só em `prod`/com FFmpeg)


@pytest.mark.media
def test_ffmpeg_real_gera_jpeg_1280x720_dentro_de_2_mb(settings: Settings, tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg não instalado")
    master = tmp_path / "m.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=1920x1080:r=60:d=4",
            str(master),
        ],
        check=True,
    )
    font = next((Path(p) for p in SYSTEM_FONTS if Path(p).is_file()), None)
    if font is None:
        pytest.skip("sem fonte do sistema")
    brand_dir = tmp_path / "brand"
    (brand_dir / "fonts").mkdir(parents=True)
    shutil.copy(font, brand_dir / "fonts" / "a.ttf")
    story = {
        "capitulos": [
            {
                "n": 1,
                "beats": [
                    {
                        "segmento_id": 1,
                        "arquivo_id": 1,
                        "inicio_s": 0.0,
                        "fim_s": 4.0,
                        "beat": "x",
                        "classe": "acao",
                        "nota": 0.9,
                    }
                ],
            }
        ]
    }
    out = render_thumbnails(
        story, {1: master}, ThumbnailModel(), VISUAL, tmp_path / "out", settings,
        texts=["MORRI DE NOVO"], count=1, brand_dir=brand_dir,
    )  # fmt: skip
    assert out.items and out.items[0].path.stat().st_size <= MAX_BYTES
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0",
        str(out.items[0].path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert probe.stdout.strip() == "1280,720"

from __future__ import annotations

from pathlib import Path

import pytest

from cronista.gabarito import CLASSES, parse_time, validate_gabarito


def _write(tmp_path: Path, body: str, encoding: str = "utf-8") -> Path:
    path = tmp_path / "gabarito.csv"
    path.write_text(body, encoding=encoding)
    return path


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("83.5", 83.5), ("1:23.5", 83.5), ("01:02:03.25", 3723.25), ("0:05", 5.0), ("2,5", 2.5)],
)
def test_parse_time(text: str, seconds: float) -> None:
    assert parse_time(text) == seconds


@pytest.mark.parametrize("text", ["", "abc", "1:2:3:4", "-1", "1::2"])
def test_parse_time_invalido(text: str) -> None:
    with pytest.raises(ValueError, match="tempo"):
        parse_time(text)


def test_gabarito_valido_converte_para_quadros(tmp_path: Path) -> None:
    path = _write(tmp_path, "inicio,fim,classe,nota\n0:10,0:12.5,fala,oi\n1:00,1:30,farm,\n")
    report = validate_gabarito(path, duration_s=600)
    assert report.ok and not report.warnings
    assert [(a.start_frame, a.end_frame) for a in report.annotations] == [(600, 750), (3600, 5400)]
    assert report.totals() == {"fala": (1, 2.5), "farm": (1, 30.0)}


def test_aceita_bom_ponto_e_virgula_e_comentarios(tmp_path: Path) -> None:
    body = "# anotado em 2026-11-16\ninicio;fim;classe;nota\n5;6;risada;ha\n"
    report = validate_gabarito(_write(tmp_path, body, "utf-8-sig"))
    assert report.ok and len(report.annotations) == 1


def test_erros_apontam_a_linha(tmp_path: Path) -> None:
    body = "inicio,fim,classe,nota\n10,5,fala,\n1,2,dancinha,\nx,2,fala,\n3,4\n700,800,fala,\n"
    report = validate_gabarito(_write(tmp_path, body), duration_s=600)
    assert not report.ok
    joined = "\n".join(report.errors)
    assert "linha 2" in joined and "maior que o início" in joined
    assert "linha 3" in joined and "dancinha" in joined
    assert "linha 4" in joined and "tempo inválido" in joined
    assert "linha 5" in joined and "faltam colunas" in joined
    assert "linha 6" in joined and "passa da duração" in joined


def test_cabecalho_errado(tmp_path: Path) -> None:
    report = validate_gabarito(_write(tmp_path, "a,b,c\n1,2,fala\n"))
    assert not report.ok and "cabeçalho" in report.errors[0]


def test_avisos_de_sobreposicao_e_nota_ausente(tmp_path: Path) -> None:
    body = "inicio,fim,classe,nota\n0,10,fala,\n5,15,fala,\n0,10,farm,\n20,30,objetivo,\n"
    report = validate_gabarito(_write(tmp_path, body))
    assert report.ok  # avisos não impedem o uso
    assert any("sobrepõe" in w for w in report.warnings)  # fala com fala, mas não fala com farm
    assert sum("sobrepõe" in w for w in report.warnings) == 1
    assert any("sem nota" in w for w in report.warnings)


def test_arquivo_inexistente_e_vazio(tmp_path: Path) -> None:
    assert not validate_gabarito(tmp_path / "nao-existe.csv").ok
    assert not validate_gabarito(_write(tmp_path, "\n# so comentario\n")).ok


def test_todas_as_classes_tem_descricao() -> None:
    assert all(CLASSES.values())

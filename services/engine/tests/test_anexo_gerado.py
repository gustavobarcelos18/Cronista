"""F14: a árvore e a lista de comandos da documentação vêm do código; o anexo não pode ficar defasado."""

from __future__ import annotations

from cronista.devtools import anexo


def test_anexo_gerado_esta_em_dia() -> None:
    current = anexo.ANEXO.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert current == anexo.render(), (
        "rode `python -m cronista.devtools.anexo` e commite docs/anexo-gerado.md"
    )


def test_anexo_lista_todos_os_comandos_e_pacotes() -> None:
    text = anexo.render()
    assert "| `montagem` |" in text and "| `ingest` |" in text
    assert "| `commands/` |" in text and "| `domain/` |" in text
    assert "| `media/` | FFmpeg" in text

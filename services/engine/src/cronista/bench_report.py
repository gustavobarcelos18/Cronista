"""Relatórios dos benchmarks em Markdown (`docs/benchmarks/`), gerados dos JSONs de `data/<env>/bench/`.

Cada relatório tem um bloco de tabelas entre marcadores, que o comando regrava sempre, e uma parte de análise
escrita à mão que fica de fora dos marcadores e nunca é apagada.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

BEGIN = "<!-- tabelas:inicio (gerado por `cronista bench-report`; não edite aqui) -->"
END = "<!-- tabelas:fim -->"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _num(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _hours(speed_x: float) -> str:
    if not speed_x:
        return "-"
    hours = 10.0 / speed_x
    if hours * 60 < 1:
        return f"{hours * 3600:.0f} s"
    return f"{hours * 60:.0f} min" if hours < 1.5 else f"{hours:.1f} h"


def table(head: list[str], rows: list[list[str]]) -> str:
    line = "| " + " | ".join(head) + " |\n|" + "|".join("---" for _ in head) + "|\n"
    return line + "\n".join("| " + " | ".join(r) + " |" for r in rows) + "\n"


def embeddings_tables(bench: Path) -> str:
    rows: list[dict[str, Any]] = []
    for name in ("video-1-leves.json", "video-1-pesados.json"):
        rows += _load(bench / name) or []
    if not rows:
        return "_Sem dados (rode `cronista bench-video`)._\n"
    ok = sorted((r for r in rows if r["speed_x"]), key=lambda r: -(r.get("zeroshot_acc") or 0))
    body = [
        [
            f"`{r['model']}`",
            str(r["dim"]),
            _hours(r["speed_x"]),
            f"{(r['vram_peak_mib'] or 0) / 1024:.1f} GB",
            _num(r.get("knn_acc")),
            _num(r.get("zeroshot_acc")),
        ]
        for r in ok
    ]
    out = table(["Modelo", "Dim.", "10 h de vídeo em", "VRAM", "kNN", "Zero-shot"], body)
    failed = [r for r in rows if not r["speed_x"]]
    if failed:
        out += "\nNão medidos: " + "; ".join(f"`{r['model']}` ({r['note'][:80]})" for r in failed) + "\n"
    return out


def speech_tables(bench: Path) -> str:
    rows = _load(bench / "audio-quality-2.json") or []
    rows = [r for r in rows if r["kind"] == "fala"]
    if not rows:
        return "_Sem dados (rode `cronista bench-audio-quality --speech ...`)._\n"
    body = [
        [
            f"`{r['candidate']}`",
            _hours(r["speed_x"]),
            f"{r['speed_x']:.1f}x",
            f"{(r['vram_peak_mib'] or 0) / 1024:.1f} GB",
            "-" if r["wer"] is None else f"{r['wer'] * 100:.1f}%",
            str(r["events"]),
        ]
        for r in rows
    ]
    return table(["Modelo", "10 h de áudio em", "x tempo real", "VRAM", "WER", "Trechos"], body)


def events_tables(bench: Path) -> str:
    rows = [r for r in (_load(bench / "audio-quality-3.json") or []) if r["kind"] == "eventos"]
    if not rows:
        return "_Sem dados (rode `cronista bench-audio-quality --events ...`)._\n"

    def pr(p: float | None, r: float | None) -> str:
        return f"{_num(p)} / {_num(r)}"

    body = [
        [
            f"`{r['candidate']}`",
            _hours(r["speed_x"]),
            f"{(r['vram_peak_mib'] or 0) / 1024:.1f} GB",
            pr(r["risada_precision"], r["risada_recall"]),
            pr(r["exclamacao_precision"], r["exclamacao_recall"]),
            str(r["events"]),
        ]
        for r in rows
    ]
    return table(
        [
            "Modelo",
            "10 h de áudio em",
            "VRAM",
            "Risada (precisão / revocação)",
            "Exclamação (P / R)",
            "Eventos",
        ],
        body,
    )


def vision_rows(bench: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    data: dict[str, Any] = {}
    for name in ("vision-1-ocr.json", "vision-1-vlm.json"):  # rodadas separadas: OCR e VLMs
        part = _load(bench / name) or {}
        # a 1ª rodada (OCR) tem linhas de VLM que falharam por falta de pacote; a dos VLMs as refaz
        rows += [r for r in part.get("rows", []) if name.endswith("vlm.json") or r["task"] == "hud"]
        data = {**data, **{k: v for k, v in part.items() if k != "rows"}}
    return rows, data


def screen_tables(bench: Path) -> str:
    rows, _ = vision_rows(bench)
    rows = [r for r in rows if r["task"] == "tela"]
    if not rows:
        return "_Sem dados (rode `cronista bench-vision`)._\n"
    body = []
    for r in rows:
        if r["note"].startswith("falhou"):
            body.append([f"`{r['candidate']}`", "-", "-", "-", "-", r["note"][:90]])
            continue
        classes = ", ".join(f"{k} {v:.2f}" for k, v in r["per_class"].items())
        body.append(
            [
                f"`{r['candidate']}`",
                r["resolution"],
                f"{r['seconds_per_item']:.2f} s",
                f"{(r['vram_peak_mib'] or 0) / 1024:.1f} GB",
                _num(r["accuracy"]),
                f"{classes}; inválidas {r['invalid']}",
            ]
        )
    return table(["Modelo", "Entrada", "Tempo/quadro", "VRAM", "Acerto", "Por classe"], body)


def hud_tables(bench: Path) -> str:
    rows, data = vision_rows(bench)
    hud = [r for r in rows if r["task"] == "hud"]
    if not hud:
        return "_Sem dados (rode `cronista bench-vision`)._\n"
    body = []
    for r in hud:
        if r["note"].startswith("falhou"):
            body.append([f"`{r['candidate']}`", "-", "-", "-", "-", "-", r["note"][:80]])
            continue
        body.append(
            [
                f"`{r['candidate']}`",
                r["resolution"],
                f"{r['seconds_per_item']:.2f} s",
                _num(r["accuracy"]),
                _num(r["cer"]),
                _num(r["day_time_ok"]),
                "",
            ]
        )
    out = table(
        [
            "Leitor",
            "Entrada",
            "Tempo/leitura",
            "Leituras boas",
            "Erro de caracteres",
            "Dia/hora certo",
            "Nota",
        ],
        body,
    )
    decode = data.get("decodificacao") or []
    if decode:
        out += "\n**Decodificação do vídeo (1 quadro por segundo):**\n\n"
        out += table(
            ["Caso", "x tempo real", "10 h em"],
            [
                [d["caso"], f"{d['x_tempo_real']:.1f}x" if d["ok"] else "falhou", _hours(d["x_tempo_real"])]
                for d in decode
            ],
        )
    return out


REPORTS: dict[str, tuple[str, str, Callable[[Path], str]]] = {
    "01-embeddings-de-quadro.md": (
        "Embeddings de quadro (contextos e busca de B-roll)",
        "bench-video",
        embeddings_tables,
    ),
    "02-fala.md": ("Transcrição de fala", "bench-audio-quality --speech", speech_tables),
    "03-eventos-sonoros.md": (
        "Eventos sonoros (risada e exclamação)",
        "bench-audio-quality --events",
        events_tables,
    ),
    "04-estado-de-tela.md": ("Estado de tela por modelo de visão e linguagem", "bench-vision", screen_tables),
    "05-hud-e-resolucao.md": ("Leitura do HUD (OCR) e efeito da resolução", "bench-vision", hud_tables),
}


def _write_block(path: Path, title: str, command: str, tables: str) -> None:
    block = f"{BEGIN}\n\n{tables}\n{END}"
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if BEGIN in text and END in text:
            head, rest = text.split(BEGIN, 1)
            _, tail = rest.split(END, 1)
            path.write_text(head + block + tail, encoding="utf-8")
            return
    path.write_text(
        f"# {title}\n\nComando: `cronista {command}`.\n\n{block}\n\n## Análise\n\n_A escrever._\n",
        encoding="utf-8",
    )


def write_reports(bench: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, (title, command, make) in REPORTS.items():
        path = out_dir / name
        _write_block(path, title, command, make(bench))
        written.append(path)
    return written

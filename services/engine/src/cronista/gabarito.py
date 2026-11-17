"""Gabarito (decisão D3): CSV `inicio,fim,classe,nota` anotado à mão, validado por este módulo.

O gabarito mede a qualidade das fases 2 em diante (WER, eventos de áudio, farm contra momento, menus).
Ele nasce em segundos (é anotado ouvindo/vendo o vídeo); a conversão para quadros inteiros a 60 fps (§38)
acontece na leitura, em `domain.frames`, para que tudo que o compara com marcadores use a mesma grade.
"""

from __future__ import annotations

import csv
import itertools
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from cronista.domain.frames import seconds_to_frame

# Classes aceitas. Várias podem se sobrepor (ex.: `fala` durante um `farm`). Quem decide o que cada uma mede
# é a fase que a consome; este conjunto é a proposta inicial (histórico §39) e cresce por decisão.
CLASSES: dict[str, str] = {
    "fala": "o criador falando (alvo do WER)",
    "risada": "risada do criador",
    "exclamacao": "exclamação ou grito de emoção alta (não se separa grito de fala empolgada; histórico §46)",
    "grito": "legado: vale como `exclamacao` (histórico §46)",
    "teclado": "som de teclado/mouse (não deve gerar evento)",
    "respiracao": "respiração/ruído de boca (não deve gerar evento)",
    "farm": "trecho repetitivo/rotina (candidato a timelapse)",
    "momento": "momento legal (deve aparecer no topo dos candidatos)",
    "menu": "menu/inventário/mapa",
    "loading": "tela de carregamento",
    "idle": "personagem parado sem ação",
    "hud_oculto": "HUD escondido de propósito (F1, modo diretor, Replay Mod)",
    "cinematica": "cinemática do jogo",
    "construcao": "construção/obra em andamento",
    "objetivo": "objetivo declarado ou implícito (Fase 5A; a nota diz qual)",
    "estado": "mudança de estado do jogo/objetivo (Fase 5A; a nota diz qual)",
}

HEADER = ("inicio", "fim", "classe", "nota")


@dataclass(frozen=True)
class Annotation:
    line: int
    start_frame: int
    end_frame: int
    cls: str
    note: str


@dataclass
class GabaritoReport:
    annotations: list[Annotation] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def totals(self) -> dict[str, tuple[int, float]]:
        """classe → (quantidade, segundos anotados)."""
        acc: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
        for a in self.annotations:
            acc[a.cls][0] += 1
            acc[a.cls][1] += (a.end_frame - a.start_frame) / 60
        return {k: (int(v[0]), v[1]) for k, v in sorted(acc.items())}


def parse_time(text: str) -> float:
    """`83.5`, `1:23.5` ou `01:02:03.25` → segundos. Levanta ValueError se não for tempo."""
    parts = text.strip().replace(",", ".").split(":")
    if not 1 <= len(parts) <= 3 or any(not p.strip() for p in parts):
        raise ValueError(f"tempo inválido: {text!r}")
    seconds = 0.0
    for p in parts:
        try:
            value = float(p)
        except ValueError:
            raise ValueError(f"tempo inválido: {text!r}") from None
        if value < 0:
            raise ValueError(f"tempo negativo: {text!r}")
        seconds = seconds * 60 + value
    return seconds


def validate_gabarito(path: Path, duration_s: float | None = None) -> GabaritoReport:
    """Lê o CSV e devolve anotações, erros (impedem o uso) e avisos (a conferir)."""
    report = GabaritoReport()
    try:
        # `utf-8-sig`: o Excel salva CSV com BOM.
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        report.errors.append(f"não consegui ler {path}: {exc}")
        return report

    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        report.errors.append("arquivo vazio")
        return report
    delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","  # Excel em pt-BR usa ;
    rows = list(csv.reader(lines, delimiter=delimiter))
    header = tuple(c.strip().lower() for c in rows[0])
    if header[: len(HEADER)] != HEADER:
        report.errors.append(f"cabeçalho deve ser {','.join(HEADER)} (veio {','.join(rows[0])})")
        return report

    for number, row in enumerate(rows[1:], start=2):
        row = [c.strip() for c in row]
        if len(row) < 3:
            report.errors.append(f"linha {number}: faltam colunas (precisa de inicio, fim, classe)")
            continue
        note = row[3] if len(row) > 3 else ""
        try:
            start, end = parse_time(row[0]), parse_time(row[1])
        except ValueError as exc:
            report.errors.append(f"linha {number}: {exc}")
            continue
        cls = row[2].lower()
        if cls not in CLASSES:
            report.errors.append(
                f"linha {number}: classe {row[2]!r} desconhecida (aceitas: {', '.join(CLASSES)})"
            )
            continue
        if end <= start:
            report.errors.append(f"linha {number}: fim ({row[1]}) deve ser maior que o início ({row[0]})")
            continue
        if duration_s is not None and end > duration_s + 0.5:
            report.errors.append(
                f"linha {number}: fim {row[1]} passa da duração do vídeo ({duration_s:.1f}s)"
            )
            continue
        if cls in {"objetivo", "estado"} and not note:
            report.warnings.append(f"linha {number}: classe {cls} sem nota (a nota diz qual objetivo/estado)")
        report.annotations.append(
            Annotation(number, seconds_to_frame(start), seconds_to_frame(end), cls, note)
        )

    by_class: dict[str, list[Annotation]] = defaultdict(list)
    for a in report.annotations:
        by_class[a.cls].append(a)
    for cls, items in by_class.items():
        items.sort(key=lambda a: a.start_frame)
        for prev, cur in itertools.pairwise(items):
            if cur.start_frame < prev.end_frame:
                report.warnings.append(f"linhas {prev.line} e {cur.line}: {cls} se sobrepõe a {cls}")
    return report

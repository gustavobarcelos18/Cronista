# ruff: noqa: E501
"""Roteiro (Fase 5): espaços sem fala ao vivo, estimativa de duração, provedores, validação, lint e SRT.

A fala ao vivo tem prioridade: o roteiro só entra nos espaços sem fala e complementa (decisão, porquê, o que
vem a seguir). Sem voz sintética. O provedor padrão é o `NullProvider` (sem texto escrito); o Claude Code
(skills `/roteirizar` e `/humanizar`) e o `LocalScriptProvider` (experimental) produzem as falas.
"""

from __future__ import annotations

import itertools
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from pydantic import BaseModel, ValidationError

from cronista.domain.evidence import AnalysisEvent
from cronista.domain.frames import FPS
from cronista.story.models import Script, ScriptLine

WORDS_PER_S = 2.6
"""Ritmo de fala natural em pt-BR (≈ 155 palavras por minuto); o perfil de voz pode ajustar."""
MIN_GAP_S = 3.0
PAD_S = 0.5


def estimate_seconds(text: str, wps: float = WORDS_PER_S) -> float:
    return round(max(len(re.findall(r"\w+", text)), 1) / wps, 1)


def free_gaps(
    start_s: float, end_s: float, speech: Sequence[AnalysisEvent], min_gap_s: float = MIN_GAP_S
) -> list[tuple[float, float]]:
    """Espaços de `[start_s, end_s]` sem fala ao vivo (com folga), onde a narração pode entrar."""
    taken = sorted(
        (e.evidence.start_frame / FPS - PAD_S, e.evidence.end_frame / FPS + PAD_S)
        for e in speech
        if e.kind == "fala" and e.evidence.end_frame / FPS > start_s and e.evidence.start_frame / FPS < end_s
    )
    gaps: list[tuple[float, float]] = []
    cursor = start_s
    for a, b in [*taken, (end_s, end_s)]:
        if a - cursor >= min_gap_s:
            gaps.append((round(cursor, 2), round(min(a, end_s), 2)))
        cursor = max(cursor, b)
    return gaps


# ---------------------------------------------------------------- lint (humanizar)

PATTERNS: dict[str, str] = {
    "nao_e_x_e_y": r"\bn[aã]o [eé] [^.,;]{2,40}[,;]? (mas )?[eé] ",
    "muleta_escrita": r"\b(vale ressaltar|nesse sentido|em suma|em resumo|cabe destacar|diga-se de passagem)\b",
    "vocabulario_inflado": r"\b(jornada|[eé]pico|[eé]pica|incr[ií]vel|monumental|verdadeiramente|surpreendente)\b",
    "autoridade_vaga": r"\b(dizem que|especialistas|todo mundo sabe|como se sabe)\b",
    "residuo_chatbot": r"\b(claro!|com certeza!|espero que ajude|como (uma )?ia|posso ajudar)\b",
    "fechamento_dramatico": r"\b(e assim,? (come[cç]ou|terminou)|nada seria como antes|o resto [eé] hist[oó]ria)\b",
    "explicar_o_obvio": r"\b(como (voc[eê]s? )?(acabaram de|podem) ver|como vimos)\b",
    "gerundio_cascata": r"\w+ndo,? \w+ndo,? \w+ndo\b",
}
_COMPILED = {k: re.compile(v, re.IGNORECASE) for k, v in PATTERNS.items()}
MAX_BREATH_WORDS = 28


def lint_text(text: str) -> list[str]:
    """Sinais de texto "de IA" para fala (adaptado do Humanizer, MIT; ver `.claude/skills/humanizar`)."""
    flags = [name for name, rx in _COMPILED.items() if rx.search(text)]
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    if any(len(re.findall(r"\w+", s)) > MAX_BREATH_WORDS for s in sentences):
        flags.append("frase_longa_demais")
    starts = [s.split()[0].lower() for s in sentences if s.split()]
    if len(starts) >= 3 and Counter(starts).most_common(1)[0][1] >= 3:
        flags.append("frases_comecando_igual")
    return flags


# ---------------------------------------------------------------- validação


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    lines: list[ScriptLine] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_script(
    script: Script,
    segments: Mapping[str, tuple[float, float, Sequence[tuple[float, float]]]],
    wps: float = WORDS_PER_S,
) -> ValidationReport:
    """`segments`: id → `(início, fim, espaços livres)`. Cada fala precisa de um segmento existente.

    Fala que não cabe nos espaços sem fala ao vivo é aviso (o criador corta); antecipação sem justificativa é erro.
    """
    report = ValidationReport()
    used: dict[str, float] = {}
    for n, line in enumerate(script.lines, start=1):
        label = f"fala {n} ({line.segment_id})"
        if line.segment_id not in segments:
            report.errors.append(f"{label}: segmento inexistente")
            continue
        if line.kind == "antecipacao" and not (line.justification and line.justification.strip()):
            report.errors.append(f"{label}: antecipação precisa de justificativa")
            continue
        est = line.est_s if line.est_s else estimate_seconds(line.text, wps)
        _, _, gaps = segments[line.segment_id]
        room = sum(b - a for a, b in gaps)
        used[line.segment_id] = used.get(line.segment_id, 0.0) + est
        if not gaps:
            report.warnings.append(f"{label}: segmento sem espaço livre de fala ao vivo")
        elif used[line.segment_id] > room:
            report.warnings.append(
                f"{label}: {used[line.segment_id]:.1f}s de fala para {room:.1f}s livres (o criador corta)"
            )
        for flag in lint_text(line.text):
            report.warnings.append(f"{label}: sinal de texto de IA ({flag})")
        report.lines.append(line.model_copy(update={"est_s": est}))
    return report


def load_script(path: Path) -> Script:
    try:
        return Script.model_validate_json(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValidationError, json.JSONDecodeError) as exc:
        raise ValueError(f"roteiro inválido em {path}: {exc}") from exc


def _srt_time(sec: float) -> str:
    ms = round(sec * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def to_srt(lines: Sequence[ScriptLine], starts: Mapping[str, float]) -> str:
    """SRT do roteiro em tempo do arquivo de origem (a Fase 6 remapeia para a timeline)."""
    blocks: list[str] = []
    for n, line in enumerate(lines, start=1):
        a = line.start_s if line.start_s is not None else starts.get(line.segment_id, 0.0)
        b = a + (line.est_s or estimate_seconds(line.text))
        tag = "[ANTECIPAÇÃO] " if line.kind == "antecipacao" else ""
        blocks.append(f"{n}\n{_srt_time(a)} --> {_srt_time(b)}\n{tag}{line.text}\n")
    return "\n".join(blocks)


# ---------------------------------------------------------------- provedores


class ScriptProvider(Protocol):
    name: str

    def write(self, pack: Mapping[str, Any]) -> Script: ...


class NullProvider:
    """Sem roteiro escrito: nenhuma fala; o contexto de cada trecho segue como marcador (fallback padrão)."""

    name = "null"

    def write(self, pack: Mapping[str, Any]) -> Script:
        return Script(provider=self.name, lines=[])


def context_notes(pack: Mapping[str, Any]) -> list[tuple[str, str]]:
    """`(segment_id, texto)` com o contexto de cada trecho, para os marcadores do Resolve sem roteiro."""
    notes: list[tuple[str, str]] = []
    for chapter in pack.get("capitulos", []):
        for beat in chapter.get("beats", []):
            reasons = "; ".join(beat.get("razoes", [])[:3])
            notes.append(
                (beat["segmento_id"], f"Cap. {chapter['n']} · {beat['beat']} · {beat['classe']} · {reasons}")
            )
    return notes


class TextGenerator(Protocol):
    """Porta do modelo local de texto (adaptador real só em `prod`)."""

    def generate(self, prompt: str, max_tokens: int) -> str: ...


class _Fala(BaseModel):
    texto: str


class LocalScriptProvider:
    """EXPERIMENTAL (histórico §40): uma fala curta por trecho, só com fatos do pacote, saída em JSON validada.

    Só vale se passar no benchmark de roteiro; o padrão continua sendo o `NullProvider`. Falas que não cabem
    no espaço livre ou com sinais de texto de IA são descartadas, nunca "consertadas" às cegas.
    """

    name = "local"

    def __init__(self, generator: TextGenerator, wps: float = WORDS_PER_S) -> None:
        self.generator = generator
        self.wps = wps

    def write(self, pack: Mapping[str, Any]) -> Script:
        lines: list[ScriptLine] = []
        for chapter in pack.get("capitulos", []):
            for beat in chapter.get("beats", []):
                gaps = [(g["inicio_s"], g["fim_s"]) for g in beat.get("lacunas", [])]
                room = sum(b - a for a, b in gaps)
                if room < MIN_GAP_S:
                    continue
                max_words = int(room * self.wps)
                facts = "; ".join([beat["beat"], beat["classe"], *beat.get("razoes", [])[:3]])
                prompt = (
                    "Escreva UMA fala curta de narração em português do Brasil, em tom falado, sobre este trecho "
                    f"de gameplay. Fatos (não invente nada além deles): {facts}. No máximo {max_words} palavras. "
                    'Responda só com JSON: {"texto": "..."}'
                )
                try:
                    raw = self.generator.generate(prompt, 4 * max_words)
                    text = _Fala.model_validate_json(raw[raw.index("{") : raw.rindex("}") + 1]).texto.strip()
                except (ValueError, ValidationError):
                    continue
                if not text or len(re.findall(r"\w+", text)) > max_words or lint_text(text):
                    continue
                lines.append(ScriptLine(segment_id=beat["segmento_id"], text=text, start_s=gaps[0][0]))
        return Script(provider=self.name, lines=lines)


# ---------------------------------------------------------------- perfil de voz


def voice_profile(quotes: Sequence[str]) -> dict[str, Any]:
    """Guia de estilo a partir das falas ao vivo do criador: tamanho de frase, bordões e palavras frequentes."""
    sentences = [s for q in quotes for s in re.split(r"[.!?]+", q) if s.strip()]
    lengths = [len(re.findall(r"\w+", s)) for s in sentences]
    words = [w for q in quotes for w in re.findall(r"[a-zà-ú]{4,}", q.lower())]
    bigrams: Counter[tuple[str, str]] = Counter()
    for q in quotes:
        tokens = re.findall(r"[a-zà-ú]+", q.lower())
        bigrams.update(itertools.pairwise(tokens))
    return {
        "frases": len(lengths),
        "palavras_por_frase": round(float(np.mean(lengths)), 1) if lengths else 0.0,
        "palavras_por_segundo": WORDS_PER_S,
        "bordoes": [" ".join(k) for k, n in bigrams.most_common(8) if n >= 3],
        "palavras_frequentes": [w for w, _ in Counter(words).most_common(12)],
    }

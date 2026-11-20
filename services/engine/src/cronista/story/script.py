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

from cronista.config import Settings
from cronista.domain.evidence import AnalysisEvent
from cronista.domain.frames import FPS
from cronista.story.models import Script, ScriptLine

WORDS_PER_S = 2.6
"""Ritmo de fala natural em pt-BR (≈ 155 palavras por minuto); o perfil de voz pode ajustar."""
MIN_GAP_S = 3.0
PAD_S = 0.5


def estimate_seconds(text: str, wps: float = WORDS_PER_S) -> float:
    return round(max(len(re.findall(r"\w+", text)), 1) / wps, 1)


HOOK_ID = "@gancho"
CLOSE_ID = "@fecho"
RESERVED_MAX_S: dict[str, float] = {HOOK_ID: 45.0, CLOSE_ID: 35.0}
"""Janelas de narração reservadas (histórico §67): o gancho abre o vídeo e o fecho o encerra. Exceção declarada à
regra "fala ao vivo primeiro": o criador grava essas duas partes à parte (as referências do canal fazem assim), então
elas não dependem de lacuna. O valor é o tempo máximo da janela, em segundos."""


def is_reserved(segment_id: str) -> bool:
    return segment_id in RESERVED_MAX_S


LIVE_KINDS = frozenset({"fala", "risada", "exclamacao", "grito"})
"""O que ocupa o áudio ao vivo: voz e emoção (risada e exclamação também não podem ser cobertas)."""


def free_gaps(
    start_s: float, end_s: float, speech: Sequence[AnalysisEvent], min_gap_s: float = MIN_GAP_S
) -> list[tuple[float, float]]:
    """Espaços de `[start_s, end_s]` sem fala ao vivo (com folga), onde a narração pode entrar."""
    taken = sorted(
        (e.evidence.start_frame / FPS - PAD_S, e.evidence.end_frame / FPS + PAD_S)
        for e in speech
        if e.kind in LIVE_KINDS
        and e.evidence.end_frame / FPS > start_s
        and e.evidence.start_frame / FPS < end_s
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
    "vocabulario_inflado": r"\b([eé]pico|[eé]pica|incr[ií]vel|monumental|verdadeiramente|surpreendente)\b",
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


SLACK_S = 0.05
"""Tolerância de arredondamento ao conferir se uma fala cabe numa lacuna."""


def _place(
    gaps: Sequence[tuple[float, float]], cursor: float, est: float
) -> tuple[float | None, tuple[float, float] | None]:
    """Primeira posição, depois de `cursor`, em que `est` segundos cabem numa lacuna; senão (None, None)."""
    for a, b in gaps:
        start = max(a, cursor)
        if start + est <= b + SLACK_S:
            return start, (a, b)
    return None, None


def _reconcile_segment_id(
    segment_id: str, segments: Mapping[str, tuple[float, float, Sequence[tuple[float, float]]]]
) -> str | None:
    """Acha o segmento atual que contém o início do id antigo (`arquivo:início_s`), no mesmo arquivo.

    O id muda quando a relevância é recalculada e a janela se desloca (B15); a fala continua valendo se o
    ponto onde ela estava ainda cai dentro de um segmento do mesmo arquivo.
    """
    file_part, _, start_part = segment_id.partition(":")
    try:
        old_start = float(start_part)
    except ValueError:
        return None
    for sid, (start, end, _gaps) in segments.items():
        if sid.partition(":")[0] == file_part and start <= old_start < end:
            return sid
    return None


def validate_script(
    script: Script,
    segments: Mapping[str, tuple[float, float, Sequence[tuple[float, float]]]],
    wps: float = WORDS_PER_S,
) -> ValidationReport:
    """`segments`: id → `(início, fim, espaços livres)`. Cada fala precisa de um segmento existente.

    A fala ao vivo tem prioridade, então o encaixe é conferido por lacuna: segmento sem lacuna e `start_s` fora
    de qualquer lacuna são erro (a fala cairia em cima da fala ao vivo). Fala sem `start_s` é encadeada, uma
    depois da outra, dentro das lacunas. Fala que passa do que cabe é aviso (o criador corta); antecipação sem
    justificativa é erro.
    """
    report = ValidationReport()
    used: dict[str, float] = {}
    cursor: dict[str, float] = {}
    for n, line in enumerate(script.lines, start=1):
        label = f"fala {n} ({line.segment_id})"
        if is_reserved(line.segment_id):
            # Janela reservada: sem lacuna a conferir; as falas se encadeiam dentro da janela (`start_s` = deslocamento).
            est = line.est_s if line.est_s else estimate_seconds(line.text, wps)
            if line.kind == "antecipacao":
                report.errors.append(f"{label}: gancho e fecho não são antecipação")
                continue
            if line.segment_id not in used:
                report.warnings.append(
                    f"{line.segment_id}: janela reservada, gravada à parte; pode cobrir fala ao vivo (o criador confere)"
                )
            offset = cursor.get(line.segment_id, 0.0)
            used[line.segment_id] = offset + est
            cursor[line.segment_id] = offset + est
            if offset + est > RESERVED_MAX_S[line.segment_id] + SLACK_S:
                report.warnings.append(
                    f"{label}: {offset + est:.1f}s para {RESERVED_MAX_S[line.segment_id]:.0f}s da janela (o criador corta)"
                )
            for flag in lint_text(line.text):
                report.warnings.append(f"{label}: sinal de texto de IA ({flag})")
            report.lines.append(line.model_copy(update={"est_s": est, "start_s": round(offset, 2)}))
            continue
        if line.segment_id not in segments:
            moved = _reconcile_segment_id(line.segment_id, segments)
            if moved is None:
                report.errors.append(f"{label}: segmento inexistente (roteiro órfão: a relevância mudou?)")
                continue
            report.warnings.append(f"{label}: segmento mudou de janela; fala religada a {moved}")
            line = line.model_copy(update={"segment_id": moved})
        if line.kind == "antecipacao" and not (line.justification and line.justification.strip()):
            report.errors.append(f"{label}: antecipação precisa de justificativa")
            continue
        est = line.est_s if line.est_s else estimate_seconds(line.text, wps)
        _, _, gaps = segments[line.segment_id]
        if not gaps:
            report.errors.append(f"{label}: segmento sem espaço livre de fala ao vivo")
            continue
        room = sum(b - a for a, b in gaps)
        used[line.segment_id] = used.get(line.segment_id, 0.0) + est
        fits = True
        if line.start_s is None:
            start, _gap = _place(gaps, cursor.get(line.segment_id, 0.0), est)
            if start is None:  # não cabe em nenhuma lacuna: entra no começo da maior e o criador corta
                fits = False
                start = max(gaps, key=lambda g: g[1] - g[0])[0]
        else:
            start = line.start_s
            inside = next(((a, b) for a, b in gaps if a - SLACK_S <= start < b), None)
            if inside is None:
                report.errors.append(
                    f"{label}: start_s {start:.1f}s cai fora dos espaços livres (fala ao vivo)"
                )
                continue
            fits = start + est <= inside[1] + SLACK_S
        if not fits:
            report.warnings.append(
                f"{label}: {used[line.segment_id]:.1f}s de fala para {room:.1f}s livres (o criador corta)"
            )
        cursor[line.segment_id] = start + est
        for flag in lint_text(line.text):
            report.warnings.append(f"{label}: sinal de texto de IA ({flag})")
        report.lines.append(line.model_copy(update={"est_s": est, "start_s": round(start, 2)}))
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
        if is_reserved(line.segment_id):
            a = starts.get(line.segment_id, 0.0) + (line.start_s or 0.0)
        else:
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
                if not gaps:
                    continue
                # Uma fala só, numa lacuna só: a maior. Somar as lacunas deixaria a fala invadir a fala ao vivo.
                gap = max(gaps, key=lambda g: g[1] - g[0])
                room = gap[1] - gap[0]
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
                lines.append(ScriptLine(segment_id=beat["segmento_id"], text=text, start_s=gap[0]))
        return Script(provider=self.name, lines=lines)


def script_provider(settings: Settings, generator: TextGenerator | None = None) -> ScriptProvider:
    """Escolhe o provedor de roteiro: `NullProvider` por padrão; o local só com benchmark aprovado e gerador."""
    if settings.script_provider == "local" and settings.script_benchmark_ok and generator is not None:
        return LocalScriptProvider(generator)
    return NullProvider()


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

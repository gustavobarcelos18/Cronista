# ruff: noqa: E501
"""Sugestões de título (Fase 9C): pacote compacto, validação, clichês e provedores.

Mesmo caminho do roteiro: o `NullTitleProvider` é o padrão (nenhum título escrito) e o Claude Code (skills `/titular` e
`/humanizar`) produz as sugestões a partir do `titulo-pack.json`. O criador escolhe e edita; o texto dele sempre
ganha do sugerido. Só fatos do pacote; nada de clichê de "isca de clique".
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from cronista.story.script import lint_text

MAX_TITLE_CHARS = 70
"""Acima disso o YouTube corta o título na busca e na lista de sugeridos."""
HARD_TITLE_CHARS = 100
"""Limite do YouTube: o título do próprio criador pode passar de 70, nunca de 100."""
MIN_TITLES = 3
MAX_TITLES = 5
MIN_THUMB_WORDS = 2
MAX_THUMB_WORDS = 4
MAX_THUMB_CHARS = 28
TOP_MOMENTS = 6
QUOTE_CHARS = 90
REASON_CHARS = 60

INSTRUCTIONS = [
    "Escreva 3 a 5 títulos, até 70 caracteres cada, em pt-BR; cada um com `reason` apontando o fato do pacote em que se apoia.",
    "Só fatos do pacote (objetivo, momentos, desfecho); nada inventado e nenhum número de dia (o dia é decidido na edição).",
    "Sem isca de clique: nada de 'você não vai acreditar', caixa alta, '!!' ou promessa que o vídeo não cumpre.",
    "Se o desfecho foi um fracasso, o título pode (e deve) assumir isso; não esconda nem dramatize.",
    "Depois de escrever, passe pela skill /humanizar.",
    "Escreva também 2 a 3 `thumbnail_texts` (2 a 4 palavras, até 28 caracteres) para a imagem de capa: fato curto, sem isca.",
]

CLICHES: dict[str, str] = {
    "nao_vai_acreditar": r"\bvoc[eê]s? n[aã]o (vai|v[aã]o) acreditar\b",
    "mudou_tudo": r"\b(isso|aquilo|ele|ela) mudou tudo\b",
    "ninguem_esperava": r"\bningu[eé]m (esperava|imaginava)\b",
    "adjetivo_isca": r"\b(chocante|inacredit[aá]vel|imperd[ií]vel|insano|absurdo)\b",
    "urgencia": r"\b(urgente|antes que (seja tarde|delete|apaguem))\b",
    "suspense_vazio": r"\bo que aconteceu (depois|a seguir|em seguida)\b",
}
_CLICHES = {k: re.compile(v, re.IGNORECASE) for k, v in CLICHES.items()}
_SHOUT = re.compile(r"\b[A-ZÀ-Ú]{4,}\b(?:\s+[A-ZÀ-Ú]+\b)+|(?:\b[A-ZÀ-Ú]+\s+)+[A-ZÀ-Ú]{4,}\b")
_EXCESS_PUNCT = re.compile(r"[!?]{2,}")


def cliche_flags(text: str) -> list[str]:
    """Sinais de título de isca de clique, além dos padrões de texto de IA do `lint_text`."""
    flags = [name for name, rx in _CLICHES.items() if rx.search(text)]
    if _SHOUT.search(text):
        flags.append("caixa_alta")
    if _EXCESS_PUNCT.search(text):
        flags.append("pontuacao_exagerada")
    return flags


# ---------------------------------------------------------------- contratos


class TitleOption(BaseModel):
    text: str = Field(min_length=1)
    reason: str | None = None
    """O fato do pacote em que o título se apoia (para o criador conferir)."""


class TitleSet(BaseModel):
    version: int = 1
    provider: str = "desconhecido"
    titles: list[TitleOption] = Field(default_factory=list)
    thumbnail_texts: list[str] = Field(default_factory=list)
    """Textos curtos (2 a 4 palavras) para a thumbnail (Fase 9B)."""


@dataclass
class TitleReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    titles: list[TitleOption] = field(default_factory=list)
    thumbnail_texts: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_titles(title_set: TitleSet) -> TitleReport:
    """Recusa título vazio, repetido, acima do limite ou com clichê; texto de IA e falta de base são avisos."""
    report = TitleReport()
    seen: set[str] = set()
    for n, option in enumerate(title_set.titles, start=1):
        text = " ".join(option.text.split())
        label = f"título {n}"
        if not text:
            report.errors.append(f"{label}: vazio")
            continue
        if len(text) > MAX_TITLE_CHARS:
            report.errors.append(f"{label}: {len(text)} caracteres (limite {MAX_TITLE_CHARS})")
            continue
        key = text.casefold()
        if key in seen:
            report.errors.append(f"{label}: repetido")
            continue
        seen.add(key)
        flags = cliche_flags(text)
        if flags:
            report.errors.append(f"{label}: clichê de isca de clique ({', '.join(flags)})")
            continue
        for flag in lint_text(text):
            report.warnings.append(f"{label}: sinal de texto de IA ({flag})")
        if not (option.reason and option.reason.strip()):
            report.warnings.append(f"{label}: sem `reason` (o fato do pacote em que se apoia)")
        report.titles.append(option.model_copy(update={"text": text}))
    _validate_thumbnail_texts(title_set, report)
    if len(title_set.titles) > MAX_TITLES:
        report.errors.append(f"{len(title_set.titles)} títulos (máximo {MAX_TITLES})")
    elif 0 < len(report.titles) < MIN_TITLES and not report.errors:
        report.warnings.append(
            f"só {len(report.titles)} título(s) (o plano pede {MIN_TITLES} a {MAX_TITLES})"
        )
    return report


def _validate_thumbnail_texts(title_set: TitleSet, report: TitleReport) -> None:
    """Texto de thumbnail: 2 a 4 palavras, até 28 caracteres, sem repetição nem clichê (erros); texto de IA é aviso."""
    seen: set[str] = set()
    for n, raw in enumerate(title_set.thumbnail_texts, start=1):
        text = " ".join(raw.split())
        label = f"texto de thumbnail {n}"
        words = len(text.split())
        if not text:
            report.errors.append(f"{label}: vazio")
        elif not MIN_THUMB_WORDS <= words <= MAX_THUMB_WORDS:
            report.errors.append(
                f"{label}: {words} palavra(s) (o plano pede {MIN_THUMB_WORDS} a {MAX_THUMB_WORDS})"
            )
        elif len(text) > MAX_THUMB_CHARS:
            report.errors.append(f"{label}: {len(text)} caracteres (limite {MAX_THUMB_CHARS})")
        elif text.casefold() in seen:
            report.errors.append(f"{label}: repetido")
        elif flags := cliche_flags(text):
            report.errors.append(f"{label}: clichê de isca de clique ({', '.join(flags)})")
        else:
            seen.add(text.casefold())
            report.thumbnail_texts.append(text)
            for flag in lint_text(text):
                report.warnings.append(f"{label}: sinal de texto de IA ({flag})")


def check_creator_thumbnail_text(text: str, max_words: int = MAX_THUMB_WORDS) -> str:
    """Texto de thumbnail do próprio criador: só o que não cabe na imagem é recusado (vazio, palavras e caracteres)."""
    clean = " ".join(text.split())
    if not clean:
        raise ValueError("texto de thumbnail vazio")
    if len(clean.split()) > max_words:
        raise ValueError(f"texto com {len(clean.split())} palavras (o modelo aceita até {max_words})")
    if len(clean) > 2 * MAX_THUMB_CHARS:
        raise ValueError(f"texto com {len(clean)} caracteres (cabem até {2 * MAX_THUMB_CHARS})")
    return clean


def check_creator_title(text: str) -> str:
    """Título do próprio criador: só o limite duro do YouTube é recusado; o resto é escolha dele."""
    clean = " ".join(text.split())
    if not clean:
        raise ValueError("título vazio")
    if len(clean) > HARD_TITLE_CHARS:
        raise ValueError(f"título com {len(clean)} caracteres (o YouTube aceita até {HARD_TITLE_CHARS})")
    return clean


def load_titles(path: Path) -> TitleSet:
    try:
        return TitleSet.model_validate_json(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValidationError, json.JSONDecodeError) as exc:
        raise ValueError(f"títulos inválidos em {path}: {exc}") from exc


# ---------------------------------------------------------------- pacote de entrada


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _moment(chapter_n: int, beat: Mapping[str, Any]) -> dict[str, Any]:
    quote = next((s["texto"] for s in beat.get("fala_ao_vivo", []) if s.get("texto")), "")
    entry: dict[str, Any] = {
        "segmento_id": beat["segmento_id"],
        "capitulo": chapter_n,
        "beat": beat["beat"],
        "classe": beat["classe"],
        "nota": beat["nota"],
        "razoes": [_short(r, REASON_CHARS) for r in beat.get("razoes", [])[:3]],
    }
    if beat.get("marcadores"):
        entry["marcadores"] = list(beat["marcadores"])
    if quote:
        entry["fala"] = _short(quote, QUOTE_CHARS)
    return entry


def build_title_pack(story_pack: Mapping[str, Any], top: int = TOP_MOMENTS) -> dict[str, Any]:
    """Recorte compacto do story-pack para titular: objetivo, arco, abertura, desfecho e os momentos de maior nota.

    Determinístico (mesma entrada, mesmo pacote) e sem número de dia; cabe em poucos milhares de caracteres.
    """
    chapters = story_pack.get("capitulos", [])
    flat = [(c["n"], b) for c in chapters for b in c.get("beats", [])]
    ranked = sorted(flat, key=lambda cb: (-float(cb[1]["nota"]), cb[1]["segmento_id"]))
    objectives = [
        {"titulo": o["titulo"], "tipo": o["tipo"], "estado": o["estado"]}
        for o in story_pack.get("objetivos", [])
        if o.get("confirmado")
    ]
    objectives.sort(key=lambda o: (o["tipo"] != "principal", o["titulo"]))
    arc = [
        {
            "capitulo": c["n"],
            "beats": dict(Counter(b["beat"] for b in c.get("beats", []))),
            "desfecho": c["beats"][-1]["beat"] if c.get("beats") else None,
        }
        for c in chapters
    ]
    return {
        "projeto": dict(story_pack.get("projeto", {})),
        "alvo_s": story_pack.get("alvo_s"),
        "objetivos": objectives,
        "arco": arc,
        "abertura": _moment(*flat[0]) if flat else None,
        "desfecho": _moment(*flat[-1]) if flat else None,
        "momentos": [_moment(n, b) for n, b in ranked[:top]],
        "limite_caracteres": MAX_TITLE_CHARS,
        "instrucoes": INSTRUCTIONS,
    }


# ---------------------------------------------------------------- provedores


class TitleProvider(Protocol):
    name: str

    def write(self, pack: Mapping[str, Any]) -> TitleSet: ...


class NullTitleProvider:
    """Sem título escrito: o criador titula sozinho (fallback padrão, como no roteiro)."""

    name = "null"

    def write(self, pack: Mapping[str, Any]) -> TitleSet:
        return TitleSet(provider=self.name, titles=[])

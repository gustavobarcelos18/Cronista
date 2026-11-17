"""`story-pack.json` (Fase 5): o recorte compacto que o roteirista (Claude Code ou modelo local) recebe.

Só fatos verificáveis: segmentos escolhidos com razões da nota, falas ao vivo (com transcrição, para o roteiro
não cobri-las), espaços livres, objetivos com estado e citação. Nunca a série inteira; cabe no plano Pro.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from cronista.domain.evidence import AnalysisEvent
from cronista.domain.frames import FPS
from cronista.story.arc import BeatedSegment, Chapter
from cronista.story.script import free_gaps

MAX_CHARS = 60_000
QUOTE_CHARS = 160
ANTICIPATION_RULE = (
    "Cronologia por padrão. Antecipação só para gerar desejo de assistir ou ilustrar narração com cinemática,"
    " sem distorcer fatos; toda antecipação sai marcada com justificativa."
)
INSTRUCTIONS = [
    "Fala ao vivo tem prioridade: nunca escreva sobre `fala_ao_vivo`; só nas `lacunas`.",
    "Fato concreto no lugar de adjetivo; não invente nada fora deste pacote.",
    "Texto falado, frases curtas, sem muletas de texto escrito; o suspense vem de fato do pacote.",
    ANTICIPATION_RULE,
]


def _beat_entry(item: BeatedSegment, speech: Sequence[AnalysisEvent], with_quotes: bool) -> dict[str, Any]:
    a, b = item.span.start_s, item.span.end_s
    live = [
        e
        for e in speech
        if e.kind == "fala" and e.evidence.end_frame / FPS > a and e.evidence.start_frame / FPS < b
    ]
    return {
        "segmento_id": item.span.segment_id,
        "arquivo_id": item.span.file_id,
        "inicio_s": a,
        "fim_s": b,
        "beat": item.beat.value,
        "classe": item.segment.classe,
        "nota": item.segment.score,
        "razoes": item.segment.razoes,
        "marcadores": item.marker_kinds,
        "fala_ao_vivo": [
            {
                "inicio_s": round(e.evidence.start_frame / FPS, 1),
                "fim_s": round(e.evidence.end_frame / FPS, 1),
                **({"texto": (e.evidence.quote or "")[:QUOTE_CHARS]} if with_quotes else {}),
            }
            for e in live
        ],
        "lacunas": [{"inicio_s": x, "fim_s": y} for x, y in free_gaps(a, b, live)],
    }


def build_story_pack(
    chapters: Sequence[Chapter],
    speech_by_file: Mapping[int, Sequence[AnalysisEvent]],
    project: Mapping[str, Any],
    objectives: Sequence[Mapping[str, Any]],
    target_s: float,
    max_chars: int = MAX_CHARS,
) -> dict[str, Any]:
    """Monta o pacote; se passar de `max_chars`, tira as transcrições dos trechos de menor nota primeiro."""

    def make(quotes_from: float) -> dict[str, Any]:
        return {
            "projeto": dict(project),
            "alvo_s": target_s,
            "objetivos": list(objectives),
            "antecipacoes": [],
            "instrucoes": INSTRUCTIONS,
            "capitulos": [
                {
                    "n": c.number,
                    "alocado_s": c.allocated_s,
                    "beats": [
                        _beat_entry(i, speech_by_file.get(i.span.file_id, ()), i.segment.score >= quotes_from)
                        for i in c.items
                    ],
                }
                for c in chapters
            ],
        }

    cutoff = 0.0
    pack = make(cutoff)
    scores = sorted({i.segment.score for c in chapters for i in c.items})
    for candidate in [*scores, 1.01]:
        if len(json.dumps(pack, ensure_ascii=False)) <= max_chars:
            break
        cutoff = candidate
        pack = make(cutoff)
    pack["truncado"] = cutoff > 0.0
    return pack

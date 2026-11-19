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
from cronista.story.models import (
    PackBeat,
    PackChapter,
    PackLiveSpeech,
    PackObjective,
    PackProject,
    PackWindow,
    StoryPack,
)
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


def _beat_entry(item: BeatedSegment, speech: Sequence[AnalysisEvent], with_quotes: bool) -> PackBeat:
    """`speech`: eventos de áudio ao vivo do arquivo (fala, risada, exclamação); as lacunas evitam todos."""
    a, b = item.span.start_s, item.span.end_s
    in_window = [e for e in speech if e.evidence.end_frame / FPS > a and e.evidence.start_frame / FPS < b]
    live = [e for e in in_window if e.kind == "fala"]
    return PackBeat(
        segmento_id=item.span.segment_id,
        arquivo_id=item.span.file_id,
        inicio_s=a,
        fim_s=b,
        beat=item.beat,
        classe=item.segment.classe,
        nota=item.segment.score,
        razoes=item.segment.razoes,
        marcadores=item.marker_kinds,
        fala_ao_vivo=[
            PackLiveSpeech(
                inicio_s=round(e.evidence.start_frame / FPS, 1),
                fim_s=round(e.evidence.end_frame / FPS, 1),
                texto=(e.evidence.quote or "")[:QUOTE_CHARS] if with_quotes else None,
            )
            for e in live
        ],
        lacunas=[PackWindow(inicio_s=x, fim_s=y) for x, y in free_gaps(a, b, in_window)],
    )


def build_story_pack(
    chapters: Sequence[Chapter],
    speech_by_file: Mapping[int, Sequence[AnalysisEvent]],
    project: Mapping[str, Any],
    objectives: Sequence[Mapping[str, Any]],
    target_s: float,
    max_chars: int = MAX_CHARS,
) -> dict[str, Any]:
    """Monta o pacote; se passar de `max_chars`, tira as transcrições dos trechos de menor nota primeiro.

    O pacote é validado como `StoryPack` e devolvido como dicionário JSON (o que os provedores leem)."""

    def make(quotes_from: float, truncated: bool = False) -> StoryPack:
        return StoryPack(
            projeto=PackProject(**project),
            alvo_s=target_s,
            objetivos=[PackObjective(**o) for o in objectives],
            instrucoes=INSTRUCTIONS,
            capitulos=[
                PackChapter(
                    n=c.number,
                    alocado_s=c.allocated_s,
                    beats=[
                        _beat_entry(i, speech_by_file.get(i.span.file_id, ()), i.segment.score >= quotes_from)
                        for i in c.items
                    ],
                )
                for c in chapters
            ],
            truncado=truncated,
        )

    def dump(pack: StoryPack) -> dict[str, Any]:
        return pack.model_dump(mode="json", exclude_none=True)

    cutoff = 0.0
    pack = make(cutoff)
    scores = sorted({i.segment.score for c in chapters for i in c.items})
    for candidate in [*scores, 1.01]:
        if len(json.dumps(dump(pack), ensure_ascii=False)) <= max_chars:
            break
        cutoff = candidate
        pack = make(cutoff)
    return dump(pack.model_copy(update={"truncado": cutoff > 0.0}))

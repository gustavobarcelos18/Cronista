"""OCR do HUD (Fase 3C-3): eventos `hud_texto` lidos só nas regiões que o perfil declara.

Sem regiões (perfil genérico) a etapa não lê nada. O texto vem de quadros do **master** a 720p, um a cada
`every_s` segundos; um evento é um trecho em que o texto da região não mudou (a citação vai em `quote`).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from cronista.audio.events import EVENTS_KEY, write_events_file
from cronista.config import Settings
from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource, params_hash
from cronista.domain.frames import FPS
from cronista.domain.models import StageResult
from cronista.pipeline.stage import StageContext, StageError
from cronista.video import frames as vframes
from cronista.video.ports import HudReader, HudRegionSpec

EVERY_S = 5.0
WIDTH, HEIGHT = 1280, 720
READS = ("text", "number")


def clean(text: str, read: str) -> str:
    """`number` guarda só dígitos e separadores; `text` só normaliza espaços."""
    text = " ".join(text.split())
    if read == "number":
        return "".join(re.findall(r"[0-9.,:/-]+", text))
    return text


def merge_reads(reads: Sequence[tuple[float, str]], every_s: float) -> list[tuple[float, float, str]]:
    """`(segundo, texto)` em ordem → `(início, fim, texto)` fundindo leituras iguais seguidas; vazio some."""
    out: list[tuple[float, float, str]] = []
    for sec, text in reads:
        if not text:
            continue
        if out and out[-1][2] == text and sec - out[-1][1] <= every_s * 1.5:
            out[-1] = (out[-1][0], sec + every_s, text)
        else:
            out.append((sec, sec + every_s, text))
    return out


def crop(frame: Any, region: HudRegionSpec) -> Any:
    h, w = frame.shape[:2]
    x0, y0 = int(region.x * w), int(region.y * h)
    return frame[
        y0 : max(y0 + 1, int((region.y + region.h) * h)), x0 : max(x0 + 1, int((region.x + region.w) * w))
    ]


class HudTextStage:
    name = "video_hud_text"
    version = "1"
    needs: tuple[str, ...] = ("normalize",)
    uses_gpu = False  # OCR em CPU (ONNX)

    def __init__(
        self,
        reader: HudReader,
        regions: Sequence[HudRegionSpec],
        every_s: float = EVERY_S,
        spans_s: Sequence[tuple[float, float]] | None = None,
    ) -> None:
        self.reader = reader
        self.regions = tuple(r for r in regions if r.read in READS)
        self.skipped = [r.name for r in regions if r.read not in READS]
        self.every_s = every_s
        self.spans_s = tuple(spans_s) if spans_s else None
        """Trechos `(início, fim)` em segundos a ler; `None` = o master inteiro."""

    def params(self, settings: Settings) -> dict[str, Any]:
        r = self.reader
        return {
            "reader": [r.name, r.version, r.options],
            "regions": [vars(x) for x in self.regions],
            "every_s": self.every_s,
            "spans": self.spans_s,
            "size": [WIDTH, HEIGHT],
        }

    def run(self, ctx: StageContext) -> StageResult:
        warnings = [
            f"região {n}: leitura não suportada (só {'/'.join(READS)}), ignorada" for n in self.skipped
        ]
        if not self.regions:
            path = write_events_file(ctx.out_dir, [])
            warnings.append("perfil sem regiões de HUD: nada a ler")
            return StageResult(files=[path], data={EVENTS_KEY: path, "count": 0}, warnings=warnings)
        # O master normalizado (remux/8 bits), não o original: um MP4 interrompido só abre depois do remux.
        master = Path(str(ctx.inputs["normalize"].data.get("media", ctx.media_path)))
        if not master.is_file():
            raise StageError(f"master não encontrado: {master}")
        reads: dict[str, list[tuple[float, str]]] = {r.name: [] for r in self.regions}
        for start, end in self.spans_s or [(0.0, None)]:
            for sec, frame in vframes.iter_frames_every(
                ctx.settings,
                master,
                every_s=self.every_s,
                width=WIDTH,
                height=HEIGHT,
                start_s=start,
                end_s=end,
            ):
                ctx.wait_for_gpu()  # pausa com o OBS gravando ou jogo em tela cheia (CLAUDE.md)
                texts = self.reader.read([crop(frame, r) for r in self.regions])
                for region, text in zip(self.regions, texts, strict=True):
                    reads[region.name].append((sec, clean(text, region.read)))
        digest = params_hash(self.params(ctx.settings))
        by_name = {r.name: r for r in self.regions}
        events: list[AnalysisEvent] = []
        for name, items in reads.items():
            for a, b, text in merge_reads(items, self.every_s):
                events.append(
                    AnalysisEvent(
                        kind="hud_texto",
                        evidence=Evidence(
                            source=EvidenceSource.CENA,
                            start_frame=round(a * FPS),
                            end_frame=round(b * FPS),
                            confidence=0.5,  # RapidOCR dá confiança por linha; ainda não usada
                            model=self.reader.name,
                            model_version=self.reader.version,
                            params_hash=digest,
                            quote=text,
                        ),
                        payload={"regiao": name, "texto": text, "tag_tema": by_name[name].tag_theme},
                    )
                )
        events.sort(key=lambda e: e.evidence.start_frame)
        path = write_events_file(ctx.out_dir, events)
        return StageResult(files=[path], data={EVENTS_KEY: path, "count": len(events)}, warnings=warnings)

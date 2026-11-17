"""VLM local em perguntas fechadas (Fase 3C-4): uma pergunta por vez, resposta validada, nunca texto livre.

O núcleo só conhece a porta `ScreenVLM`; o Qwen3-VL real é adaptador (`adapters/qwen_vl.py`, só `prod`, GPU).
Cada pergunta lista as respostas possíveis e o modelo responde `{"answer": "<opção>"}`, validado por Pydantic
contra essas opções. Resposta fora das opções vira `None` (conta como inválida, nunca como palpite).
Usos (histórico §49): (a) nomear cada **tipo** de menu (uma pergunta por tipo, não por menu), (b) desempate de
estado de tela duvidoso, (c) confirmar tema de B-roll candidato.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from pydantic import BaseModel, ValidationError, create_model

from cronista.audio.events import EVENTS_KEY, write_events_file
from cronista.config import Settings
from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource, params_hash
from cronista.domain.models import StageResult
from cronista.pipeline.stage import StageContext, StageError
from cronista.video import frames as vframes
from cronista.video.ports import RgbImage

IMAGE_SIZE = (640, 360)
"""Quadro 360p entregue ao modelo (histórico §49)."""


class ScreenVLM(Protocol):
    name: str
    options: dict[str, Any]

    @property
    def version(self) -> str: ...

    def ask(self, image: RgbImage, prompt: str, max_new_tokens: int = 24) -> str:
        """Resposta crua do modelo a `prompt` sobre `image` `(altura, largura, 3)` RGB."""
        ...


@dataclass(frozen=True)
class Question:
    key: str
    text: str
    choices: tuple[str, ...]

    def prompt(self) -> str:
        options = ", ".join(f'"{c}"' for c in self.choices)
        return (
            f"{self.text} Reply only with JSON like "
            f'{{"answer": "<option>"}}, where option is one of: {options}.'
        )

    def schema(self) -> dict[str, Any]:
        return answer_model(self.choices).model_json_schema()


MENU_KIND = Question(
    "menu_kind",
    "This is a screenshot of a video game. What kind of interface screen is it?",
    ("inventory", "map", "settings", "dialogue", "crafting", "pause", "other"),
)
SCREEN_STATE = Question(
    "screen_state",
    "This is a screenshot of a video game. What is on screen?",
    ("gameplay", "menu", "loading", "cutscene", "other"),
)
ENEMY_PRESENT = Question(
    "enemy_present", "Is there an enemy or hostile creature in this image?", ("yes", "no")
)


def answer_model(choices: Sequence[str]) -> type[BaseModel]:
    """Modelo Pydantic `{answer: Literal[...opções]}`; também gera o JSON Schema da pergunta."""
    literal = Literal[tuple(choices)]  # type: ignore[valid-type]
    fields: Any = {"answer": (literal, ...)}
    return create_model("Answer", **fields)


_JSON = re.compile(r"\{.*?\}", re.DOTALL)


def parse_answer(raw: str, choices: Sequence[str]) -> str | None:
    """Valida a resposta contra as opções. Aceita o JSON pedido; se vier texto, só se citar UMA opção."""
    model = answer_model(choices)
    for chunk in _JSON.findall(raw):
        try:
            return str(cast(Any, model.model_validate(json.loads(chunk))).answer)
        except (ValueError, ValidationError):
            continue
    lowered = raw.lower()
    hits = [c for c in choices if re.search(rf"\b{re.escape(c.lower())}\b", lowered)]
    return hits[0] if len(hits) == 1 else None


def ask_choice(vlm: ScreenVLM, image: RgbImage, question: Question) -> str | None:
    return parse_answer(vlm.ask(image, question.prompt(), 24), question.choices)


class MenuNamesStage:
    """Eventos `menu_nome`: o nome (tipo de interface) de cada tipo de menu, uma pergunta por tipo."""

    name = "video_menu_names"
    version = "1"
    needs: tuple[str, ...] = ("proxy", "video_menu_types")
    uses_gpu = True

    def __init__(self, vlm: ScreenVLM, question: Question = MENU_KIND) -> None:
        self.vlm = vlm
        self.question = question

    def params(self, settings: Settings) -> dict[str, Any]:
        v = self.vlm
        return {
            "vlm": [v.name, v.version, v.options],
            "question": [self.question.text, self.question.choices],
        }

    def run(self, ctx: StageContext) -> StageResult:
        types: list[dict[str, Any]] = list(ctx.inputs["video_menu_types"].data.get("types", []))
        if not types:
            path = write_events_file(ctx.out_dir, [])
            return StageResult(files=[path], data={EVENTS_KEY: path, "count": 0})
        proxy = Path(str(ctx.inputs["proxy"].data.get("proxy", "")))
        if not proxy.is_file():
            raise StageError(f"proxy não encontrado: {proxy} (rode a ingestão de novo)")
        digest = params_hash(self.params(ctx.settings))
        events: list[AnalysisEvent] = []
        invalid = 0
        for t in types:
            ctx.wait_for_gpu()
            frame = int(t["representative_frame"])
            image = vframes.read_rgb_frame(ctx.settings, proxy, frame, *IMAGE_SIZE)
            answer = ask_choice(self.vlm, image, self.question)
            if answer is None:
                invalid += 1
                continue
            events.append(
                AnalysisEvent(
                    kind="menu_nome",
                    evidence=Evidence(
                        source=EvidenceSource.CENA,
                        start_frame=frame,
                        end_frame=frame,
                        confidence=0.5,
                        model=self.vlm.name,
                        model_version=self.vlm.version,
                        params_hash=digest,
                    ),
                    payload={"tipo_id": int(t["id"]), "nome": answer, "menus_no_tipo": int(t["menus"])},
                )
            )
        path = write_events_file(ctx.out_dir, events)
        warnings = [f"{invalid} tipo(s) de menu com resposta inválida do VLM, sem nome"] if invalid else []
        return StageResult(files=[path], data={EVENTS_KEY: path, "count": len(events)}, warnings=warnings)

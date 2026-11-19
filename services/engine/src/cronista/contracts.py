"""Gera o JSON Schema dos contratos (decisão D2: Pydantic é a fonte; o TypeScript é gerado a partir dele)."""

from __future__ import annotations

import json
from typing import Any

from pydantic import TypeAdapter

from cronista.api.schemas import (
    DecisionIn,
    EffectSettingIn,
    EffectSettingOut,
    EventOut,
    ExportStatusOut,
    FeedbackIn,
    FeedbackOut,
    FinishDecisionIn,
    FinishingOut,
    FinishItemOut,
    JobOut,
    LearningOut,
    MarkerOut,
    MediaFileOut,
    ProgressOut,
    ScriptOut,
    SegmentOut,
    SessionOut,
    ShortDecisionIn,
    ThumbnailChoiceIn,
    TitleChoiceIn,
    WaveformOut,
)
from cronista.domain.models import MarkerKind, MediaProbe, StageResult
from cronista.packaging.panel import PackagingOut, PublishOut
from cronista.review.panel import ProjectPanelOut, SeriesPanelOut, SeriesRowOut


def _without_field_titles(node: object) -> object:
    """Tira o `title` que o Pydantic põe em cada campo: o gerador de TypeScript o usa de nome de tipo
    (`EndS`, `Decision1`...). O título do modelo (nível do `$defs`) fica."""
    if isinstance(node, dict):
        return {
            key: _without_field_titles(value)
            for key, value in node.items()
            if not (key == "title" and isinstance(value, str))
        }
    if isinstance(node, list):
        return [_without_field_titles(item) for item in node]
    return node


def build_schema() -> dict[str, object]:
    defs: dict[str, Any] = {}
    for model in (
        MediaProbe,
        StageResult,
        MediaFileOut,
        SessionOut,
        JobOut,
        MarkerOut,
        SegmentOut,
        DecisionIn,
        FeedbackIn,
        FeedbackOut,
        LearningOut,
        ProgressOut,
        SeriesRowOut,
        ProjectPanelOut,
        SeriesPanelOut,
        ExportStatusOut,
        ScriptOut,
        EventOut,
        WaveformOut,
        EffectSettingIn,
        EffectSettingOut,
        FinishItemOut,
        FinishingOut,
        FinishDecisionIn,
        PackagingOut,
        PublishOut,
        TitleChoiceIn,
        ThumbnailChoiceIn,
        ShortDecisionIn,
    ):
        schema = model.model_json_schema(ref_template="#/$defs/{model}")
        defs.update(schema.pop("$defs", {}))
        defs[model.__name__] = schema
    defs = {
        name: {k: v if k == "title" else _without_field_titles(v) for k, v in body.items()}
        for name, body in defs.items()
    }
    kind = TypeAdapter(MarkerKind).json_schema()
    defs["MarkerKind"] = kind
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "CronistaContracts",
        "$defs": dict(sorted(defs.items())),
    }


def render_schema() -> str:
    return json.dumps(build_schema(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> None:
    """Escreve `packages/contracts/schema.json` (caminho relativo à raiz do repositório)."""
    from cronista.config import find_repo_root

    target = find_repo_root() / "packages" / "contracts" / "schema.json"
    target.write_text(render_schema(), encoding="utf-8")
    print(f"Escrito {target}")


if __name__ == "__main__":
    main()

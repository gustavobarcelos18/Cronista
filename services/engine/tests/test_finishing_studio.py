"""Ajustes e decisões do acabamento no Studio (8E): tabelas só de inserção, API e reexportação."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cronista.api.app import create_app
from cronista.assembly.plan import EditPlan
from cronista.config import Settings
from cronista.db.models import FinishingDecision, FinishingSetting, MediaFile, Project, RecordingSession
from cronista.domain.tracks import Track as FxTrack
from cronista.finishing.brand import BrandKit, ResolvedStyle, SeriesStyle, resolve_style
from cronista.finishing.effects import EffectKind, EffectMode
from cronista.finishing.library import Library
from cronista.finishing.overrides import (
    current_item_decisions,
    current_settings,
    record_item_decision,
    record_setting,
    source_of,
    with_overrides,
)
from cronista.finishing.plan import FinishItem, FinishPlan

BRAND = BrandKit.model_validate(
    {
        "name": "t",
        "visual": {
            "palette": {
                "primary": "#112233",
                "secondary": "#223344",
                "accent": "#334455",
                "background": "#101010",
                "text": "#FFFFFF",
            },
            "fonts": {"title": "T", "body": "B"},
        },
    }
)


def style(series: str = "") -> ResolvedStyle:
    if not series:
        return resolve_style(BRAND)
    return resolve_style(
        BRAND, SeriesStyle.model_validate({"name": series, "effects": {"zoom": {"max_per_minute": 1}}})
    )


def seed(db: Session) -> None:
    project = Project(name="serie")
    session = RecordingSession(project=project, folder="pasta")
    db.add_all([project, session, MediaFile(session=session, path="C:/x/a.mp4", ordinal=0, size_bytes=10)])
    db.commit()


def finish_plan() -> FinishPlan:
    def item(kind: EffectKind, start: int, mode: EffectMode, track: FxTrack) -> FinishItem:
        return FinishItem(
            f"{kind.value}-{start}", kind, mode, track, start, 90, 0.7, 1, "m", None, {}, "motivo"
        )

    return FinishPlan(
        items=[
            item(EffectKind.ZOOM, 300, EffectMode.EDITAVEL, FxTrack.V2),
            item(EffectKind.SHAKE, 900, EffectMode.SUGERIR, FxTrack.V2),
        ],
        warnings=["aviso do plano"],
    )


def test_settings_are_insert_only_and_last_one_wins(db: Session) -> None:
    seed(db)
    record_setting(db, 1, EffectKind.ZOOM, EffectMode.SUGERIR, 1.0, 0.6)
    record_setting(db, 1, EffectKind.ZOOM, EffectMode.RENDERIZADO, 3.0, 0.5)
    assert db.query(FinishingSetting).count() == 2
    current = current_settings(db, 1)
    assert (
        current[EffectKind.ZOOM].mode == EffectMode.RENDERIZADO
        and current[EffectKind.ZOOM].max_per_minute == 3.0
    )
    assert current_settings(db, 99) == {}
    with pytest.raises(ValueError):
        record_setting(
            db, 1, EffectKind.ZOOM, EffectMode.EDITAVEL, 500.0, 0.5
        )  # acima do limite do brand kit
    assert db.query(FinishingSetting).count() == 2


def test_with_overrides_and_source(db: Session) -> None:
    base = style("serie-x")
    overrides = {
        EffectKind.SHAKE: base.policy(EffectKind.SHAKE).model_copy(update={"mode": EffectMode.EDITAVEL})
    }
    merged = with_overrides(base, overrides)
    assert merged.policy(EffectKind.SHAKE).mode == EffectMode.EDITAVEL
    assert base.policy(EffectKind.SHAKE).mode == EffectMode.SUGERIR  # o original não muda
    assert source_of(EffectKind.SHAKE, base, overrides) == "criador"
    assert source_of(EffectKind.ZOOM, base, overrides) == "serie"
    assert source_of(EffectKind.SFX, base, overrides) == "padrao"
    assert source_of(EffectKind.ZOOM, style(), {}) == "padrao"


def test_item_decisions_last_wins_and_padrao_clears(db: Session) -> None:
    seed(db)
    record_item_decision(db, 1, "shake-900", EffectKind.SHAKE, "aceito")
    record_item_decision(db, 1, "zoom-300", EffectKind.ZOOM, "removido")
    assert current_item_decisions(db, 1) == {"shake-900": "aceito", "zoom-300": "removido"}
    record_item_decision(db, 1, "zoom-300", EffectKind.ZOOM, "padrao")
    assert current_item_decisions(db, 1) == {"shake-900": "aceito"}
    assert db.query(FinishingDecision).count() == 3
    with pytest.raises(ValueError):
        record_item_decision(db, 1, "x-1", EffectKind.ZOOM, "talvez")


def client_with(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    calls: list[object] = []

    def fake_build(_db: object, _sid: int, _s: object, st: ResolvedStyle, *_a: object) -> FinishPlan:
        calls.append(st)
        return finish_plan()

    assembled: list[int] = []

    def fake_assemble(_db: object, session_id: int, *_a: object) -> tuple[EditPlan, SimpleNamespace]:
        assembled.append(session_id)
        return EditPlan(), SimpleNamespace(chapters=[])

    monkeypatch.setattr("cronista.api.app.build_finishing", fake_build)
    monkeypatch.setattr("cronista.api.app.assemble", fake_assemble)
    loader = lambda: (style("serie-x"), Library())  # noqa: E731
    app = create_app(settings, finishing_loader=loader)
    app.state.calls = calls
    app.state.assembled = assembled
    return TestClient(app)


def test_api_preview_settings_and_decisions(
    settings: Settings, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(db)
    client = client_with(settings, monkeypatch)

    first = client.get("/sessions/1/finishing").json()
    assert first["enabled"] and first["series"] == "serie-x" and first["has_library"]
    assert first["warnings"] == ["aviso do plano"]
    zoom = next(e for e in first["effects"] if e["kind"] == "zoom")
    assert zoom["source"] == "serie" and zoom["max_per_minute"] == 1.0
    shake = next(i for i in first["items"] if i["kind"] == "shake")
    assert shake["mode"] == "sugerir" and shake["effective_mode"] == "sugerir" and shake["decision"] is None

    put = client.put(
        "/projects/1/finishing/effects/shake",
        json={"mode": "editavel", "max_per_minute": 2, "min_score": 0.7},
    )
    assert put.status_code == 200 and put.json()["source"] == "criador" and put.json()["mode"] == "editavel"
    assert (
        client.put(
            "/projects/9/finishing/effects/shake",
            json={"mode": "sugerir", "max_per_minute": 1, "min_score": 0.5},
        ).status_code
        == 404
    )
    assert (
        client.put(
            "/projects/1/finishing/effects/shake",
            json={"mode": "sugerir", "max_per_minute": 99, "min_score": 0.5},
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/projects/1/finishing/effects/inexistente",
            json={"mode": "sugerir", "max_per_minute": 1, "min_score": 0.5},
        ).status_code
        == 422
    )

    assert (
        client.post("/sessions/1/finishing/items/shake-900/decision", json={"decision": "aceito"}).status_code
        == 200
    )
    assert (
        client.post(
            "/sessions/1/finishing/items/zoom-300/decision", json={"decision": "removido"}
        ).status_code
        == 200
    )
    assert (
        client.post("/sessions/1/finishing/items/xx-1/decision", json={"decision": "aceito"}).status_code
        == 404  # não está no plano atual
    )
    assert (
        client.post("/sessions/9/finishing/items/zoom-300/decision", json={"decision": "aceito"}).status_code
        == 404
    )
    assert (
        client.post("/sessions/1/finishing/items/zoom-300/decision", json={"decision": "talvez"}).status_code
        == 422
    )

    after = client.get("/sessions/1/finishing").json()
    items = {i["id"]: i for i in after["items"]}
    assert items["shake-900"]["decision"] == "aceito" and items["shake-900"]["effective_mode"] == "editavel"
    assert items["zoom-300"]["decision"] == "removido" and items["zoom-300"]["effective_mode"] is None
    used = client.app.state.calls[-1]  # type: ignore[attr-defined]
    assert used.policy(EffectKind.SHAKE).mode == EffectMode.EDITAVEL  # a prévia usa o ajuste do Studio
    assert client.get("/sessions/99/finishing").status_code == 404


def test_api_without_finishing_configured(settings: Settings, db: Session) -> None:
    seed(db)
    client = TestClient(create_app(settings))
    assert client.get("/sessions/1/finishing").json() == {
        "enabled": False,
        "series": "",
        "max_effects_per_minute": 0.0,
        "has_library": False,
        "effects": [],
        "items": [],
        "summary": {},
        "warnings": [],
    }
    body = {"mode": "sugerir", "max_per_minute": 1, "min_score": 0.5}
    assert client.put("/projects/1/finishing/effects/zoom", json=body).status_code == 409


def test_reexport_passes_overrides_and_decisions(
    settings: Settings, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cronista.review import reexport

    seed(db)
    record_setting(db, 1, EffectKind.SHAKE, EffectMode.EDITAVEL, 2.0, 0.7)
    record_item_decision(db, 1, "zoom-300@m", EffectKind.ZOOM, "removido")
    seen: dict[str, object] = {}

    def fake_export(*args: object, **_k: object) -> SimpleNamespace:
        seen["args"] = args
        return SimpleNamespace(
            directory=Path("x"), version=1, reused=False, problems=[], warnings=[], clips=1
        )

    monkeypatch.setattr(reexport, "export_montagem", fake_export)
    monkeypatch.setattr(reexport, "build_gate", lambda _s: None)
    library = Library()
    jobs = reexport.ReexportJobs(settings, None, lambda: (style(), library))
    assert jobs.start(1, 1800.0)
    assert isinstance(jobs.last_thread, threading.Thread)
    jobs.last_thread.join(5)
    assert jobs.status(1).state == "done"
    args = seen["args"]
    assert isinstance(args, tuple)
    sent_style, sent_library, sent_decisions = args[8], args[9], args[10]
    assert isinstance(sent_style, ResolvedStyle)
    assert sent_style.policy(EffectKind.SHAKE).mode == EffectMode.EDITAVEL
    assert sent_library is library and sent_decisions == {"zoom-300@m": "removido"}


def test_reexport_without_finishing_keeps_old_call(
    settings: Settings, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cronista.review import reexport

    seed(db)
    seen: dict[str, object] = {}

    def fake_export(*args: object, **_k: object) -> SimpleNamespace:
        seen["args"] = args
        return SimpleNamespace(
            directory=Path("x"), version=1, reused=False, problems=[], warnings=[], clips=1
        )

    monkeypatch.setattr(reexport, "export_montagem", fake_export)
    monkeypatch.setattr(reexport, "build_gate", lambda _s: None)
    jobs = reexport.ReexportJobs(settings)
    assert jobs.start(1, 1800.0)
    assert isinstance(jobs.last_thread, threading.Thread)
    jobs.last_thread.join(5)
    assert seen["args"][8:] == (None, None, None)  # type: ignore[index]


def test_preview_reuses_the_assembly_until_the_database_changes(
    settings: Settings, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cronista.db.models import Marker

    seed(db)
    client = client_with(settings, monkeypatch)
    for _ in range(3):  # prévia, ajuste e decisão não refazem a montagem
        assert client.get("/sessions/1/finishing").status_code == 200
    client.put(
        "/projects/1/finishing/effects/zoom", json={"mode": "sugerir", "max_per_minute": 1, "min_score": 0.5}
    )
    client.post("/sessions/1/finishing/items/zoom-300/decision", json={"decision": "removido"})
    assert client.app.state.assembled == [1]  # type: ignore[attr-defined]

    client.get("/sessions/1/finishing?target_min=30")  # outro alvo: outra montagem
    assert client.app.state.assembled == [1, 1]  # type: ignore[attr-defined]

    media = db.query(MediaFile).one()
    db.add(Marker(session_id=1, media_file_id=media.id, marker_id="9", kind="morte_falha", media_frame=600))
    db.commit()  # um marcador novo muda a montagem
    client.get("/sessions/1/finishing")
    assert client.app.state.assembled == [1, 1, 1]  # type: ignore[attr-defined]


def test_decision_is_bound_to_the_moment_not_only_to_the_id(
    settings: Settings, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(db)
    client = client_with(settings, monkeypatch)
    client.post("/sessions/1/finishing/items/zoom-300/decision", json={"decision": "removido"})
    assert current_item_decisions(db, 1) == {"zoom-300@m": "removido"}

    # O plano muda e o mesmo id cai em outro momento: a decisão antiga não vale para ele.
    def other_plan(*_a: object) -> FinishPlan:
        plan = finish_plan()
        plan.items[0] = FinishItem(
            "zoom-300",
            EffectKind.ZOOM,
            EffectMode.EDITAVEL,
            FxTrack.V2,
            300,
            90,
            0.7,
            1,
            "outro",
            None,
            {},
            "m",
        )
        return plan

    monkeypatch.setattr("cronista.api.app.build_finishing", other_plan)
    item = next(i for i in client.get("/sessions/1/finishing").json()["items"] if i["id"] == "zoom-300")
    assert item["decision"] is None and item["effective_mode"] == "editavel"

"""HTTP-level tests for the two required endpoints.

``app.pipeline.interpret_notes`` is monkeypatched here so this suite is fast,
deterministic, and needs no live network call or API key -- interpretation
correctness is already covered by test_ensemble.py (mocked provider) and
evals/run_interpretation.py (the live model). This file's job is the wiring:
status codes, response shape, and that nothing sensitive leaks into a body.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from app import pipeline
from app.contracts import Directive, ErrorCategory, GridWiseError, InterpretationSample

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "fixtures"
CASE = json.loads((FIXTURES / "public_cases.json").read_text())["cases"][0]
STUB_DIRECTIVES = json.loads((FIXTURES / "stub_interpretation.json").read_text())["SAMPLE-01"]

VALID_BATTERY = dict(
    capacity_kwh=300, initial_energy_kwh=150, minimum_energy_kwh=30,
    max_charge_kwh_per_hour=80, max_discharge_kwh_per_hour=80,
)
VALID_HOURS = [
    dict(hour=h, demand_kwh=100.0, solar_kwh=50.0, tariff_bdt_per_kwh=10.0) for h in range(24)
]


def base_payload(**overrides) -> dict:
    payload = dict(
        scenario_id="TEST-01",
        operator_notes=["Do not charge between 2 and 4 PM."],
        hours=[dict(h) for h in VALID_HOURS],
        battery=dict(VALID_BATTERY),
    )
    payload.update(overrides)
    return payload


def _typed_directives() -> list[Directive]:
    from pydantic import TypeAdapter

    return TypeAdapter(list[Directive]).validate_python(STUB_DIRECTIVES)


@pytest.fixture
def client(monkeypatch):
    """TestClient with interpret_notes stubbed to a canned, valid sample."""

    async def fake_interpret_notes(request, settings, provider, trace=None, deadline=None):
        return [InterpretationSample(directives=_typed_directives(), weight=1.0)]

    monkeypatch.setattr(pipeline, "interpret_notes", fake_interpret_notes)

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def failing_client(monkeypatch):
    """Same as ``client``, but the energy half raises -- exercises the 500 path."""

    async def fake_interpret_notes(request, settings, provider, trace=None, deadline=None):
        return [InterpretationSample(directives=_typed_directives(), weight=1.0)]

    monkeypatch.setattr(pipeline, "interpret_notes", fake_interpret_notes)
    monkeypatch.setattr(pipeline, "plan_energy", _raise_replay_failure)

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def _raise_replay_failure(request, samples):
    raise GridWiseError(ErrorCategory.replay_failure, "replay rejected the candidate schedule")


# --- health --------------------------------------------------------------------


def test_health_returns_ok_with_no_dependencies(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- happy path ------------------------------------------------------------


def test_valid_request_returns_200_with_echoed_scenario_id(client):
    response = client.post("/optimize-energy", json=CASE["input"])
    assert response.status_code == 200
    body = response.json()
    assert body["scenario_id"] == CASE["input"]["scenario_id"]


def test_directive_interpretation_is_in_note_index_order(client):
    response = client.post("/optimize-energy", json=CASE["input"])
    body = response.json()
    indexes = [d["note_index"] for d in body["directive_interpretation"]]
    assert indexes == sorted(indexes) == list(range(len(indexes)))


def test_response_has_24_hour_plan(client):
    response = client.post("/optimize-energy", json=CASE["input"])
    body = response.json()
    assert len(body["hourly_plan"]) == 24
    assert [h["hour"] for h in body["hourly_plan"]] == list(range(24))


# --- 400: structurally invalid request --------------------------------------


def test_malformed_json_body_is_400(client):
    response = client.post(
        "/optimize-energy",
        content=b"{not valid json at all",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


def test_zero_notes_is_400(client):
    response = client.post("/optimize-energy", json=base_payload(operator_notes=[]))
    assert response.status_code == 400


def test_four_notes_is_400(client):
    response = client.post(
        "/optimize-energy", json=base_payload(operator_notes=["a", "b", "c", "d"])
    )
    assert response.status_code == 400


def test_23_hours_is_400(client):
    payload = base_payload(hours=[dict(h) for h in VALID_HOURS[:23]])
    response = client.post("/optimize-energy", json=payload)
    assert response.status_code == 400


def test_duplicate_hour_is_400(client):
    hours = [dict(h) for h in VALID_HOURS]
    hours[5]["hour"] = hours[4]["hour"]
    response = client.post("/optimize-energy", json=base_payload(hours=hours))
    assert response.status_code == 400


def test_missing_battery_is_400(client):
    payload = base_payload()
    del payload["battery"]
    response = client.post("/optimize-energy", json=payload)
    assert response.status_code == 400


def test_400_body_never_contains_a_stack_trace(client):
    response = client.post("/optimize-energy", json=base_payload(operator_notes=[]))
    detail = json.dumps(response.json())
    assert "Traceback" not in detail
    assert "File \"" not in detail


# --- 500: internal / downstream failure --------------------------------------


def test_replay_failure_is_500_not_a_fabricated_plan(failing_client):
    response = failing_client.post("/optimize-energy", json=CASE["input"])
    assert response.status_code == 500
    assert response.json()["error"] == "replay_failure"


def test_500_body_has_no_stack_trace_or_internals(failing_client):
    response = failing_client.post("/optimize-energy", json=CASE["input"])
    detail = json.dumps(response.json())
    assert "Traceback" not in detail
    assert "GridWiseError" not in detail
    assert "File \"" not in detail


def test_unexpected_exception_becomes_generic_500(monkeypatch):
    """Exercises app.main's catch-all handler, not TestClient's own re-raise.

    TestClient defaults to raise_server_exceptions=True, which propagates an
    unhandled exception straight into the test for easier debugging -- it
    bypasses the actual Starlette exception-handling path. That default is
    right for most tests, but this one specifically verifies the fallback
    handler, so it needs raise_server_exceptions=False to see what a real
    client over HTTP would actually receive.
    """

    async def boom(request, settings, provider, trace=None, deadline=None):
        raise RuntimeError("unexpected internal failure with sensitive detail xyz123")

    monkeypatch.setattr(pipeline, "interpret_notes", boom)

    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.post("/optimize-energy", json=CASE["input"])

    assert response.status_code == 500
    detail = json.dumps(response.json())
    assert "xyz123" not in detail
    assert "RuntimeError" not in detail
    assert "Traceback" not in detail


# --- no secret material in any response body ----------------------------------


def test_no_response_body_contains_the_configured_api_key(client):
    from app.config import get_settings

    key = get_settings().llm_api_key
    responses = [
        client.get("/health"),
        client.post("/optimize-energy", json=CASE["input"]),
        client.post("/optimize-energy", json=base_payload(operator_notes=[])),
    ]
    for response in responses:
        assert key not in response.text

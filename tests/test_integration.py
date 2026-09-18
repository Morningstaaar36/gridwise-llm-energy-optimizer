"""End-to-end integration across the merged system (G4 B4.3).

Two tiers:

* **Hermetic** (default): drives the full real pipeline -- guardrails,
  compiler, LP, lattice/selection, replay -- with only the model call faked.
  Everything downstream of interpretation is the production code path, so a
  regression in the energy half fails here without needing a network call.
* **Live** (``-m live``): hits the real provider. Skipped unless LLM_API_KEY
  is set, because it costs quota and is rate-limit sensitive. The full
  10-case live gate lives in ``evals/run_public.py``; these are the smoke
  tests worth having in the suite itself.
"""

from __future__ import annotations

import json
import os
import pathlib

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from app import pipeline
from app.contracts import Directive, EnergyRequest, InterpretationSample

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "fixtures"
CASES = json.loads((FIXTURES / "public_cases.json").read_text())["cases"]
STUB_INTERP = json.loads((FIXTURES / "stub_interpretation.json").read_text())
TOLERANCE = 0.01


def _samples_for(case_id: str) -> list[InterpretationSample]:
    directives = TypeAdapter(list[Directive]).validate_python(STUB_INTERP[case_id])
    return [InterpretationSample(directives=directives, weight=1.0)]


def replay_plan(request: EnergyRequest, plan: list[dict]) -> list[str]:
    """Independent replay, rebuilt from the raw request only."""
    hours = {h.hour: h for h in request.hours}
    battery = request.battery
    violations: list[str] = []
    energy = battery.initial_energy_kwh

    for entry in plan:
        h = entry["hour"]
        action, magnitude = entry["battery_action"], entry["battery_kwh"]
        charge = magnitude if action == "charge" else 0.0
        discharge = magnitude if action == "discharge" else 0.0

        if action == "idle" and abs(magnitude) > TOLERANCE:
            violations.append(f"h{h}: idle with magnitude {magnitude}")
        if charge > battery.max_charge_kwh_per_hour + TOLERANCE:
            violations.append(f"h{h}: charge exceeds rate limit")
        if discharge > battery.max_discharge_kwh_per_hour + TOLERANCE:
            violations.append(f"h{h}: discharge exceeds rate limit")

        balance = (
            entry["grid_kwh"] + entry["solar_used_kwh"] + discharge
            - hours[h].demand_kwh - charge
        )
        if abs(balance) > TOLERANCE:
            violations.append(f"h{h}: energy balance off by {balance:.4f}")

        energy += charge - discharge
        if abs(energy - entry["battery_energy_after_kwh"]) > TOLERANCE:
            violations.append(f"h{h}: battery state mismatch")
        if not (
            battery.minimum_energy_kwh - TOLERANCE
            <= energy
            <= battery.capacity_kwh + TOLERANCE
        ):
            violations.append(f"h{h}: battery energy {energy:.4f} out of bounds")

    if abs(energy - battery.initial_energy_kwh) > TOLERANCE:
        violations.append("end-of-day battery energy != initial")
    return violations


@pytest.fixture
def client_with_fixed_interpretation(monkeypatch):
    """Real pipeline end to end; only the model call is replaced."""
    captured: dict[str, str] = {}

    async def fake_interpret_notes(request, settings, provider, trace=None, deadline=None):
        captured["scenario_id"] = request.scenario_id
        return _samples_for(request.scenario_id)

    monkeypatch.setattr(pipeline, "interpret_notes", fake_interpret_notes)

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


# --- hermetic: real compiler + LP + selection + replay -----------------------


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_every_public_case_produces_a_valid_optimal_plan(case, client_with_fixed_interpretation):
    response = client_with_fixed_interpretation.post("/optimize-energy", json=case["input"])
    assert response.status_code == 200, response.text
    body = response.json()

    request = EnergyRequest(**case["input"])
    assert replay_plan(request, body["hourly_plan"]) == []

    reference = case["expected_output"]["total_cost_bdt"]
    assert body["total_cost_bdt"] == pytest.approx(reference, abs=TOLERANCE)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_reported_totals_match_the_returned_plan(case, client_with_fixed_interpretation):
    """The judge recomputes these from hourly_plan; they must not drift."""
    body = client_with_fixed_interpretation.post(
        "/optimize-energy", json=case["input"]
    ).json()
    plan = body["hourly_plan"]
    hours = {h["hour"]: h for h in case["input"]["hours"]}

    assert body["total_grid_kwh"] == pytest.approx(
        sum(p["grid_kwh"] for p in plan), abs=TOLERANCE
    )
    assert body["peak_grid_kwh"] == pytest.approx(
        max(p["grid_kwh"] for p in plan), abs=TOLERANCE
    )
    assert body["total_cost_bdt"] == pytest.approx(
        sum(p["grid_kwh"] * hours[p["hour"]]["tariff_bdt_per_kwh"] for p in plan),
        abs=TOLERANCE,
    )


def test_scenario_id_and_note_order_survive_the_round_trip(client_with_fixed_interpretation):
    case = CASES[0]
    body = client_with_fixed_interpretation.post(
        "/optimize-energy", json=case["input"]
    ).json()
    assert body["scenario_id"] == case["input"]["scenario_id"]
    indexes = [d["note_index"] for d in body["directive_interpretation"]]
    assert indexes == list(range(len(case["input"]["operator_notes"])))


# --- live: real provider, skipped without credentials ------------------------

live = pytest.mark.skipif(
    not os.environ.get("LLM_API_KEY"),
    reason="live provider test; set LLM_API_KEY to run",
)


@live
@pytest.mark.live
def test_live_model_interprets_the_first_public_case():
    from app.main import app

    case = CASES[0]
    with TestClient(app) as test_client:
        response = test_client.post("/optimize-energy", json=case["input"])
    assert response.status_code == 200, response.text
    body = response.json()

    expected = {
        d["note_index"]: d for d in case["expected_output"]["directive_interpretation"]
    }
    for directive in body["directive_interpretation"]:
        reference = expected[directive["note_index"]]
        assert directive["directive_type"] == reference["directive_type"]
        assert directive["applies"] == reference["applies"]

"""Wire-format contract tests.

Guardrail-level validation (directive semantics, note mapping, numeric ranges)
lives in test_guardrails.py. This file tests app.contracts in isolation: the
discriminated union, the round trip against every public fixture, and the
structural invariants FastAPI relies on to produce 400s before a request ever
reaches the pipeline.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from pydantic import ValidationError

from app.contracts import (
    Directive,
    EnergyRequest,
    EnergyResponse,
    ErrorCategory,
    GridWiseError,
)

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "fixtures"
CASES = json.loads((FIXTURES / "public_cases.json").read_text())["cases"]

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


# --- round trip against every public fixture ---------------------------------


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_every_public_request_round_trips(case):
    request = EnergyRequest(**case["input"])
    again = EnergyRequest.model_validate_json(request.model_dump_json())
    assert again == request


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_every_public_expected_output_round_trips(case):
    response = EnergyResponse(**case["expected_output"])
    again = EnergyResponse.model_validate_json(response.model_dump_json())
    assert again == response


# --- EnergyRequest structural invariants (what makes malformed input a 400) --


def test_zero_notes_rejected():
    with pytest.raises(ValidationError):
        EnergyRequest(**base_payload(operator_notes=[]))


def test_four_notes_rejected():
    with pytest.raises(ValidationError):
        EnergyRequest(**base_payload(operator_notes=["a", "b", "c", "d"]))


def test_blank_note_rejected():
    with pytest.raises(ValidationError):
        EnergyRequest(**base_payload(operator_notes=[""]))


def test_23_hours_rejected():
    with pytest.raises(ValidationError):
        EnergyRequest(**base_payload(hours=[dict(h) for h in VALID_HOURS[:23]]))


def test_25_hours_rejected():
    extra = dict(VALID_HOURS[0])
    extra["hour"] = 24
    with pytest.raises(ValidationError):
        EnergyRequest(**base_payload(hours=[dict(h) for h in VALID_HOURS] + [extra]))


def test_duplicate_hour_rejected():
    hours = [dict(h) for h in VALID_HOURS]
    hours[5]["hour"] = hours[4]["hour"]  # hour 4 appears twice, hour 5 is missing
    with pytest.raises(ValidationError):
        EnergyRequest(**base_payload(hours=hours))


def test_negative_demand_rejected():
    hours = [dict(h) for h in VALID_HOURS]
    hours[0]["demand_kwh"] = -1
    with pytest.raises(ValidationError):
        EnergyRequest(**base_payload(hours=hours))


def test_unknown_top_level_field_rejected():
    with pytest.raises(ValidationError):
        EnergyRequest(**base_payload(unexpected_field=True))


def test_blank_scenario_id_rejected():
    with pytest.raises(ValidationError):
        EnergyRequest(**base_payload(scenario_id="   "))


def test_battery_initial_below_minimum_rejected():
    battery = dict(VALID_BATTERY, initial_energy_kwh=10, minimum_energy_kwh=30)
    with pytest.raises(ValidationError):
        EnergyRequest(**base_payload(battery=battery))


def test_battery_initial_above_capacity_rejected():
    battery = dict(VALID_BATTERY, initial_energy_kwh=500, capacity_kwh=300)
    with pytest.raises(ValidationError):
        EnergyRequest(**base_payload(battery=battery))


def test_valid_payload_parses():
    request = EnergyRequest(**base_payload())
    assert request.scenario_id == "TEST-01"
    assert len(request.hours) == 24


# --- Directive discriminated union --------------------------------------------


def test_no_op_forbids_applies_true():
    with pytest.raises(ValidationError):
        Directive_validate = __import__("pydantic").TypeAdapter(Directive)
        Directive_validate.validate_python(
            {"note_index": 0, "applies": True, "directive_type": "no_op",
             "structured_adjustment": None, "explanation": "x"}
        )


def test_solar_reduction_forbids_null_adjustment():
    from pydantic import TypeAdapter

    adapter = TypeAdapter(Directive)
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {"note_index": 0, "applies": True, "directive_type": "solar_reduction",
             "structured_adjustment": None, "explanation": "x"}
        )


def test_unknown_directive_type_forbidden_by_union():
    from pydantic import TypeAdapter

    adapter = TypeAdapter(Directive)
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {"note_index": 0, "applies": True, "directive_type": "curtail_everything",
             "structured_adjustment": {"hours": [1]}, "explanation": "x"}
        )


# --- GridWiseError -------------------------------------------------------------


def test_gridwise_error_carries_category_and_message():
    error = GridWiseError(ErrorCategory.provider_failure, "model unavailable")
    assert error.category is ErrorCategory.provider_failure
    assert str(error) == "model unavailable"

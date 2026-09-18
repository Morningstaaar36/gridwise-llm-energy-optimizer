import json
from pathlib import Path

import pytest

from app.contracts import EnergyRequest
from app.energy import response as response_module
from app.energy.compiler import compile_constraints
from app.energy.optimizer import solve_energy
from app.verification.replay import replay
from tests.stubs.fake_interpreter import ground_truth_samples

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
_PUBLIC_CASES = json.loads((_FIXTURES / "public_cases.json").read_text())["cases"]


def _valid_plan(case_id: str):
    case = next(c for c in _PUBLIC_CASES if c["id"] == case_id)
    request = EnergyRequest(**case["input"])
    sample = ground_truth_samples(case_id)
    tensor = compile_constraints(request, sample.directives)
    result = solve_energy(request, tensor)
    assert result.success
    plan = response_module.build(request, sample.directives, result)
    return request, sample.directives, plan


@pytest.mark.parametrize("case", _PUBLIC_CASES, ids=lambda c: c["id"])
def test_replay_passes_on_every_valid_public_plan(case):
    request, directives, plan = _valid_plan(case["id"])
    report = replay(request, directives, plan)
    assert report.ok, report.violations
    assert report.max_residual < 0.01


# --- Mandatory mutation test: corrupt a valid plan five ways, replay must catch all five. ---


def test_replay_catches_mutated_grid_value():
    request, directives, plan = _valid_plan("SAMPLE-02")
    mutated = plan.model_copy(deep=True)
    mutated.hourly_plan[5].grid_kwh += 50.0
    report = replay(request, directives, mutated)
    assert not report.ok


def test_replay_catches_grid_cap_breach():
    request, directives, plan = _valid_plan("SAMPLE-07")
    cap_directive = next(d for d in directives if d.directive_type == "max_grid_window")
    hour = cap_directive.structured_adjustment.hours[0]
    mutated = plan.model_copy(deep=True)
    mutated.hourly_plan[hour].grid_kwh = cap_directive.structured_adjustment.max_grid_kwh + 50.0
    report = replay(request, directives, mutated)
    assert not report.ok
    assert any("grid-cap" in v for v in report.violations)


def test_replay_catches_corrupted_final_battery_energy():
    request, directives, plan = _valid_plan("SAMPLE-02")
    mutated = plan.model_copy(deep=True)
    mutated.hourly_plan[23].battery_energy_after_kwh += 25.0
    report = replay(request, directives, mutated)
    assert not report.ok


def test_replay_catches_mismatched_total_cost():
    request, directives, plan = _valid_plan("SAMPLE-01")
    mutated = plan.model_copy(deep=True)
    mutated.total_cost_bdt += 500.0
    report = replay(request, directives, mutated)
    assert not report.ok
    assert any("total_cost_bdt" in v for v in report.violations)


def test_replay_catches_nonzero_action_turned_idle():
    request, directives, plan = _valid_plan("SAMPLE-02")
    mutated = plan.model_copy(deep=True)
    nonzero_hour = next(
        h for h, entry in enumerate(mutated.hourly_plan) if entry.battery_action != "idle"
    )
    mutated.hourly_plan[nonzero_hour].battery_action = "idle"
    mutated.hourly_plan[nonzero_hour].battery_kwh = 0.0
    report = replay(request, directives, mutated)
    assert not report.ok


def test_replay_catches_idle_with_nonzero_magnitude():
    request, directives, plan = _valid_plan("SAMPLE-02")
    mutated = plan.model_copy(deep=True)
    idle_hour = next(
        h for h, entry in enumerate(mutated.hourly_plan) if entry.battery_action == "idle"
    )
    mutated.hourly_plan[idle_hour].battery_kwh = 5.0
    report = replay(request, directives, mutated)
    assert not report.ok
    assert any("idle" in v for v in report.violations)


def test_replay_catches_solar_over_effective_ceiling():
    request, directives, plan = _valid_plan("SAMPLE-01")  # has a solar_reduction directive
    solar_directive = next(d for d in directives if d.directive_type == "solar_reduction")
    hour = solar_directive.structured_adjustment.hours[0]
    mutated = plan.model_copy(deep=True)
    mutated.hourly_plan[hour].solar_used_kwh += 1000.0
    report = replay(request, directives, mutated)
    assert not report.ok
    assert any("solar" in v for v in report.violations)

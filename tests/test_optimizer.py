import json
from pathlib import Path

import numpy as np
import pytest

from app.contracts import ConstraintTensor, EnergyRequest
from app.energy.compiler import compile_constraints
from app.energy.optimizer import solve_energy
from tests.stubs.fake_interpreter import ground_truth_samples

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
_PUBLIC_CASES = json.loads((_FIXTURES / "public_cases.json").read_text())["cases"]


@pytest.mark.parametrize("case", _PUBLIC_CASES, ids=lambda c: c["id"])
def test_matches_published_reference_cost(case):
    request = EnergyRequest(**case["input"])
    sample = ground_truth_samples(case["id"])
    tensor = compile_constraints(request, sample.directives)
    result = solve_energy(request, tensor)
    assert result.success
    assert result.cost == pytest.approx(case["expected_output"]["total_cost_bdt"], abs=0.01)


def test_end_of_day_neutrality_holds():
    request = EnergyRequest(**next(c for c in _PUBLIC_CASES if c["id"] == "SAMPLE-02")["input"])
    sample = ground_truth_samples("SAMPLE-02")
    tensor = compile_constraints(request, sample.directives)
    result = solve_energy(request, tensor)
    assert result.energy[-1] == pytest.approx(request.battery.initial_energy_kwh, abs=1e-6)


def test_bounds_respected():
    request = EnergyRequest(**next(c for c in _PUBLIC_CASES if c["id"] == "SAMPLE-07")["input"])
    sample = ground_truth_samples("SAMPLE-07")
    tensor = compile_constraints(request, sample.directives)
    result = solve_energy(request, tensor)
    assert np.all(result.grid >= -1e-6)
    assert np.all(result.grid <= tensor.grid + 1e-6)
    assert np.all(result.solar >= -1e-6)
    assert np.all(result.solar <= tensor.solar + 1e-6)
    assert np.all(result.flow >= -tensor.discharge - 1e-6)
    assert np.all(result.flow <= tensor.charge + 1e-6)
    assert np.all(result.energy >= tensor.reserve - 1e-6)
    assert np.all(result.energy <= request.battery.capacity_kwh + 1e-6)


def test_negative_battery_flow_bound_is_set_explicitly():
    """linprog defaults every variable to (0, None); without an explicit
    negative lower bound on `b`, discharging would be impossible and every
    public case's true (cheaper) optimum would be unreachable."""
    request = EnergyRequest(**next(c for c in _PUBLIC_CASES if c["id"] == "SAMPLE-01")["input"])
    sample = ground_truth_samples("SAMPLE-01")
    tensor = compile_constraints(request, sample.directives)
    result = solve_energy(request, tensor)
    assert result.success
    assert np.any(result.flow < -1e-6)


def test_infeasible_tensor_returns_controlled_failure():
    request = EnergyRequest(**next(c for c in _PUBLIC_CASES if c["id"] == "SAMPLE-01")["input"])
    bad_tensor = ConstraintTensor(
        solar=np.zeros(24),
        reserve=np.full(24, request.battery.capacity_kwh + 1.0),
        charge=np.zeros(24),
        discharge=np.zeros(24),
        grid=np.full(24, np.inf),
    )
    result = solve_energy(request, bad_tensor)
    assert result.success is False
    assert np.all(np.isnan(result.grid))
    assert np.isnan(result.cost)


def test_duals_are_shaped_per_hour_when_present():
    request = EnergyRequest(**next(c for c in _PUBLIC_CASES if c["id"] == "SAMPLE-05")["input"])
    sample = ground_truth_samples("SAMPLE-05")
    tensor = compile_constraints(request, sample.directives)
    result = solve_energy(request, tensor)
    assert result.duals is not None
    for key in ("balance", "battery_state", "grid", "solar", "charge", "discharge", "reserve"):
        assert result.duals[key].shape == (24,)

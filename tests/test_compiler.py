import json
from pathlib import Path

import numpy as np
import pytest

from app.contracts import EnergyRequest, InterpretationSample
from app.energy.compiler import compile_constraints

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
_PUBLIC_CASES = json.loads((_FIXTURES / "public_cases.json").read_text())["cases"]


def _request(**overrides) -> EnergyRequest:
    hours = overrides.pop(
        "hours",
        [
            {"hour": h, "demand_kwh": 10.0, "solar_kwh": 20.0, "tariff_bdt_per_kwh": 5.0}
            for h in range(24)
        ],
    )
    battery = overrides.pop(
        "battery",
        {
            "capacity_kwh": 200.0,
            "initial_energy_kwh": 100.0,
            "minimum_energy_kwh": 10.0,
            "max_charge_kwh_per_hour": 30.0,
            "max_discharge_kwh_per_hour": 30.0,
        },
    )
    return EnergyRequest(
        scenario_id=overrides.pop("scenario_id", "TEST"),
        operator_notes=overrides.pop("operator_notes", ["n1"]),
        hours=hours,
        battery=battery,
    )


def _directive(note_index, directive_type, adjustment, applies=True):
    return {
        "note_index": note_index,
        "applies": applies,
        "directive_type": directive_type,
        "structured_adjustment": adjustment,
        "explanation": "x",
    }


def _sample(*directives) -> InterpretationSample:
    return InterpretationSample(directives=list(directives))


def test_no_directives_leaves_base_bounds():
    request = _request()
    tensor = compile_constraints(request, [])
    assert np.array_equal(tensor.solar, np.full(24, 20.0))
    assert np.array_equal(tensor.reserve, np.full(24, 10.0))
    assert np.array_equal(tensor.charge, np.full(24, 30.0))
    assert np.array_equal(tensor.discharge, np.full(24, 30.0))
    assert np.all(np.isinf(tensor.grid))


def test_no_op_is_a_true_no_op():
    request = _request()
    sample = _sample(_directive(0, "no_op", None, applies=False))
    tensor = compile_constraints(request, sample.directives)
    assert np.array_equal(tensor.solar, np.full(24, 20.0))
    assert np.all(np.isinf(tensor.grid))


def test_reserve_as_50_percent_of_capacity():
    request = _request(battery={
        "capacity_kwh": 200.0, "initial_energy_kwh": 150.0, "minimum_energy_kwh": 0.0,
        "max_charge_kwh_per_hour": 30.0, "max_discharge_kwh_per_hour": 30.0,
    })
    adjustment = {"hours": [18, 19], "minimum_energy_kwh": 100.0}
    sample = _sample(_directive(0, "minimum_battery_reserve", adjustment))
    tensor = compile_constraints(request, sample.directives)
    assert tensor.reserve[18] == 100.0
    assert tensor.reserve[19] == 100.0
    assert tensor.reserve[0] == 0.0  # untouched hours keep the base floor


def test_reserve_takes_max_of_base_and_directive():
    request = _request()  # base minimum_energy_kwh = 10.0
    adjustment = {"hours": [5], "minimum_energy_kwh": 5.0}
    sample = _sample(_directive(0, "minimum_battery_reserve", adjustment))
    tensor = compile_constraints(request, sample.directives)
    assert tensor.reserve[5] == 10.0  # directive is looser than the base floor


def test_no_charge_window_leaves_discharge_untouched():
    request = _request()
    sample = _sample(_directive(0, "no_charge_window", {"hours": [6, 7]}))
    tensor = compile_constraints(request, sample.directives)
    assert tensor.charge[6] == 0.0 and tensor.charge[7] == 0.0
    assert tensor.discharge[6] == 30.0 and tensor.discharge[7] == 30.0


def test_no_discharge_window_leaves_charge_untouched():
    request = _request()
    sample = _sample(_directive(0, "no_discharge_window", {"hours": [6]}))
    tensor = compile_constraints(request, sample.directives)
    assert tensor.discharge[6] == 0.0
    assert tensor.charge[6] == 30.0


def test_grid_cap_applies_to_all_imports_including_charging():
    request = _request()
    sample = _sample(_directive(0, "max_grid_window", {"hours": [3], "max_grid_kwh": 12.0}))
    tensor = compile_constraints(request, sample.directives)
    assert tensor.grid[3] == 12.0
    # The compiler does not distinguish import purpose: the LP's balance
    # equation is what ties grid imports to charging, not the tensor.
    assert tensor.grid[4] == np.inf


def test_multiple_grid_caps_take_the_minimum():
    request = _request()
    sample = _sample(
        _directive(0, "max_grid_window", {"hours": [3], "max_grid_kwh": 15.0}),
        _directive(1, "max_grid_window", {"hours": [3], "max_grid_kwh": 12.0}),
    )
    tensor = compile_constraints(request, sample.directives)
    assert tensor.grid[3] == 12.0


def test_overlapping_solar_reduction_composes_by_product():
    request = _request()
    sample = _sample(
        _directive(0, "solar_reduction", {"hours": [8], "factor": 0.5}),
        _directive(1, "solar_reduction", {"hours": [8], "factor": 0.4}),
    )
    tensor = compile_constraints(request, sample.directives)
    assert tensor.solar[8] == pytest.approx(20.0 * 0.5 * 0.4)


def test_solar_reduction_only_affects_listed_hours():
    request = _request()
    sample = _sample(_directive(0, "solar_reduction", {"hours": [8], "factor": 0.5}))
    tensor = compile_constraints(request, sample.directives)
    assert tensor.solar[8] == 10.0
    assert tensor.solar[7] == 20.0
    assert tensor.solar[9] == 20.0


def test_compiler_ignores_hour_list_order_in_request():
    hours = [
        {"hour": h, "demand_kwh": 10.0, "solar_kwh": float(h), "tariff_bdt_per_kwh": 5.0}
        for h in reversed(range(24))
    ]
    request = _request(hours=hours)
    tensor = compile_constraints(request, [])
    assert list(tensor.solar) == [float(h) for h in range(24)]


def test_fresh_arrays_each_call_do_not_alias_or_leak():
    request = _request()
    sample = _sample(_directive(0, "solar_reduction", {"hours": [8], "factor": 0.5}))
    first = compile_constraints(request, sample.directives)
    second = compile_constraints(request, [])
    assert second.solar[8] == 20.0  # unaffected by the first call's mutation
    first.solar[0] = -999.0
    third = compile_constraints(request, [])
    assert third.solar[0] == 20.0  # mutating a returned tensor doesn't leak either


@pytest.mark.parametrize("case", _PUBLIC_CASES, ids=lambda c: c["id"])
def test_compiles_clean_against_every_public_case_ground_truth(case):
    request = EnergyRequest(**case["input"])
    directives = case["expected_output"]["directive_interpretation"]
    sample = InterpretationSample(directives=directives)
    tensor = compile_constraints(request, sample.directives)
    assert tensor.solar.shape == (24,)
    assert np.all(tensor.reserve <= request.battery.capacity_kwh)

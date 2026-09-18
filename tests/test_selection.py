import json
from pathlib import Path

import pytest

from app.contracts import EnergyRequest, ErrorCategory, GridWiseError
from app.energy import selection
from app.energy.selection import _expected_score, plan_energy
from tests.stubs.fake_interpreter import disagreeing_samples, ground_truth_samples

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
_PUBLIC_CASES = json.loads((_FIXTURES / "public_cases.json").read_text())["cases"]
_SAMPLE_01 = next(c for c in _PUBLIC_CASES if c["id"] == "SAMPLE-01")


@pytest.mark.parametrize("case", _PUBLIC_CASES, ids=lambda c: c["id"])
def test_plan_energy_matches_reference_on_every_public_case(case):
    request = EnergyRequest(**case["input"])
    sample = ground_truth_samples(case["id"])
    response, report = plan_energy(request, [sample])
    assert report.ok, report.violations
    ref = case["expected_output"]["total_cost_bdt"]
    assert response.total_cost_bdt == pytest.approx(ref, abs=0.01)
    assert [d.note_index for d in response.directive_interpretation] == list(
        range(len(sample.directives))
    )


def test_hedge_reproduces_the_measured_clamp_premium():
    """The recorded worst-case measurement put SAMPLE-01's hedge at exactly
    39730 BDT (nominal 38365, +3.558%) using 4 candidates built the same way
    as tests/stubs/fake_interpreter.disagreeing_samples()."""
    request = EnergyRequest(**_SAMPLE_01["input"])
    response, report = plan_energy(request, disagreeing_samples())
    assert report.ok
    assert response.total_cost_bdt == pytest.approx(39730.0, abs=0.01)


def test_hedge_reports_the_argmax_reading_not_a_blend():
    request = EnergyRequest(**_SAMPLE_01["input"])
    response, _ = plan_energy(request, disagreeing_samples())
    solar_directive = response.directive_interpretation[0]
    assert solar_directive.structured_adjustment.hours == [12, 13]
    assert solar_directive.structured_adjustment.factor == pytest.approx(0.25)


def test_hedge_disabled_ships_the_argmax_plan_unchanged(monkeypatch):
    monkeypatch.setattr(selection, "HEDGE_ENABLED", False)
    request = EnergyRequest(**_SAMPLE_01["input"])
    response, report = plan_energy(request, disagreeing_samples())
    assert report.ok
    # without hedging, cost is exactly the argmax-only nominal (38365), not the
    # hedged 39730 the meet across candidates would produce
    assert response.total_cost_bdt == pytest.approx(38365.0, abs=0.01)


def test_single_agreeing_sample_never_triggers_hedging_machinery():
    request = EnergyRequest(**_SAMPLE_01["input"])
    sample = ground_truth_samples("SAMPLE-01")
    response, report = plan_energy(request, [sample, sample, sample])
    assert report.ok
    assert response.total_cost_bdt == pytest.approx(38365.0, abs=0.01)


def test_plan_summary_never_claims_unverified_savings():
    request = EnergyRequest(**_SAMPLE_01["input"])
    sample = ground_truth_samples("SAMPLE-01")
    response, _ = plan_energy(request, [sample])
    assert "sav" not in response.plan_summary.lower()


def test_infeasible_argmax_raises_controlled_error():
    request = EnergyRequest(**_SAMPLE_01["input"])
    over_capacity = {
        "note_index": 0,
        "applies": True,
        "directive_type": "minimum_battery_reserve",
        "structured_adjustment": {
            "hours": list(range(24)),
            "minimum_energy_kwh": request.battery.capacity_kwh + 1.0,
        },
        "explanation": "impossible reserve",
    }
    no_op = {
        "note_index": 1,
        "applies": False,
        "directive_type": "no_op",
        "structured_adjustment": None,
        "explanation": "irrelevant",
    }
    from app.contracts import InterpretationSample

    bad_sample = InterpretationSample(directives=[over_capacity, no_op])
    with pytest.raises(GridWiseError) as exc_info:
        plan_energy(request, [bad_sample])
    assert exc_info.value.category == ErrorCategory.infeasible


def test_expected_score_formula():
    # E(T) = q_T * (25 + 10 * min(1, c_argmax / c_T))
    full = _expected_score(coverage=1.0, nominal_cost=100.0, candidate_cost=100.0)
    half = _expected_score(coverage=0.5, nominal_cost=100.0, candidate_cost=100.0)
    assert full == pytest.approx(35.0)
    assert half == pytest.approx(17.5)
    # a more expensive candidate scores lower than a cheaper one at equal coverage
    cheap = _expected_score(coverage=0.6, nominal_cost=100.0, candidate_cost=100.0)
    expensive = _expected_score(coverage=0.6, nominal_cost=100.0, candidate_cost=200.0)
    assert cheap > expensive


def test_expected_score_never_exceeds_35_times_coverage():
    for candidate_cost in (1.0, 50.0, 100.0, 1000.0):
        score = _expected_score(coverage=1.0, nominal_cost=100.0, candidate_cost=candidate_cost)
        assert score <= 35.0 + 1e-9

import json
from pathlib import Path

import pytest

from app.contracts import EnergyRequest, InterpretationSample
from app.energy.canonical import canonicalize
from tests.stubs.fake_interpreter import disagreeing_samples, ground_truth_samples

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
_PUBLIC_CASES = json.loads((_FIXTURES / "public_cases.json").read_text())["cases"]
_SAMPLE_01 = next(c for c in _PUBLIC_CASES if c["id"] == "SAMPLE-01")


def test_disagreeing_samples_form_three_classes_with_expected_posterior():
    request = EnergyRequest(**_SAMPLE_01["input"])
    candidates = canonicalize(request, disagreeing_samples())

    assert len(candidates) == 3
    posteriors = sorted((c.posterior for c in candidates), reverse=True)
    assert posteriors == pytest.approx([0.6, 0.2, 0.2], abs=1e-9)
    # descending order is a documented guarantee, not incidental
    assert [c.posterior for c in candidates] == sorted(
        (c.posterior for c in candidates), reverse=True
    )


def test_argmax_candidate_carries_the_majority_reading():
    request = EnergyRequest(**_SAMPLE_01["input"])
    candidates = canonicalize(request, disagreeing_samples())
    argmax = candidates[0]
    assert argmax.posterior == pytest.approx(0.6)
    # the majority reading kept hours [12, 13] and factor 0.25
    adjustment = argmax.directives[0].structured_adjustment
    assert adjustment.hours == [12, 13]
    assert adjustment.factor == pytest.approx(0.25)


def test_identical_samples_collapse_to_one_class():
    request = EnergyRequest(**_SAMPLE_01["input"])
    gt = ground_truth_samples("SAMPLE-01")
    candidates = canonicalize(request, [gt, gt, gt])
    assert len(candidates) == 1
    assert candidates[0].posterior == pytest.approx(1.0)


def test_vacuous_directive_disagreement_still_collapses():
    """A no-charge window on an hour where charging is already impossible
    changes no bound, so two textually different samples must land in the
    same tensor class."""
    request = EnergyRequest(
        scenario_id="TEST",
        operator_notes=["n1"],
        hours=[
            {"hour": h, "demand_kwh": 10.0, "solar_kwh": 20.0, "tariff_bdt_per_kwh": 5.0}
            for h in range(24)
        ],
        battery={
            "capacity_kwh": 200.0,
            "initial_energy_kwh": 100.0,
            "minimum_energy_kwh": 10.0,
            "max_charge_kwh_per_hour": 0.0,  # charging already impossible everywhere
            "max_discharge_kwh_per_hour": 30.0,
        },
    )
    sample_with_op = InterpretationSample(
        directives=[
            {
                "note_index": 0,
                "applies": True,
                "directive_type": "no_charge_window",
                "structured_adjustment": {"hours": [5]},
                "explanation": "x",
            }
        ]
    )
    sample_no_op = InterpretationSample(
        directives=[
            {
                "note_index": 0,
                "applies": False,
                "directive_type": "no_op",
                "structured_adjustment": None,
                "explanation": "irrelevant",
            }
        ]
    )
    candidates = canonicalize(request, [sample_with_op, sample_no_op])
    assert len(candidates) == 1
    assert candidates[0].posterior == pytest.approx(1.0)


def test_weighted_blend_favors_higher_confidence_cluster():
    request = EnergyRequest(**_SAMPLE_01["input"])
    gt = ground_truth_samples("SAMPLE-01")
    disagreeing = disagreeing_samples()
    high_confidence_minority = InterpretationSample(
        directives=[d.model_dump() for d in disagreeing[4].directives], weight=3.0
    )
    candidates = canonicalize(request, [gt, gt, gt, high_confidence_minority])
    # 3 identical ground-truth samples at default weight (0.75 frequency) vs.
    # 1 minority sample (0.25 frequency) carrying a much higher weight: with
    # pure frequency the minority would sit at 0.25, but the weight signal
    # should pull its posterior above that, without any special-casing.
    minority = next(
        c
        for c in candidates
        if c.directives[0].structured_adjustment.factor == pytest.approx(0.75)
    )
    assert minority.posterior > 0.25


@pytest.mark.parametrize("case", _PUBLIC_CASES, ids=lambda c: c["id"])
def test_canonicalize_runs_clean_on_every_public_case(case):
    request = EnergyRequest(**case["input"])
    sample = ground_truth_samples(case["id"])
    candidates = canonicalize(request, [sample])
    assert len(candidates) == 1
    assert candidates[0].posterior == pytest.approx(1.0)

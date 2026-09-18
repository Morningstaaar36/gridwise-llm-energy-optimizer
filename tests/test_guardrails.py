"""Guardrail rejection coverage.

Every rejection reason named in TASKS.md S2.4 gets a case here. The point of
this file is adversarial: model output is untrusted, so each test asserts we
*refuse* rather than silently repair.
"""

from __future__ import annotations

import copy
import json
import pathlib

import pytest

from app.contracts import EnergyRequest, ErrorCategory, GridWiseError
from app.interpretation.guardrails import validate

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "fixtures"
CASES = json.loads((FIXTURES / "public_cases.json").read_text())["cases"]
STUB_INTERP = json.loads((FIXTURES / "stub_interpretation.json").read_text())

# A two-note scenario with a solar_reduction at index 0 and a no_op at index 1.
BASE_CASE = CASES[0]
BASE_REQUEST = EnergyRequest(**BASE_CASE["input"])
BASE_ENTRIES = STUB_INTERP["SAMPLE-01"]


def envelope(entries):
    return {"reasoning": "scratch", "directive_interpretation": entries}


def mutate(index=0, **changes):
    """Copy the reference entries and patch one entry's top-level fields."""
    entries = copy.deepcopy(BASE_ENTRIES)
    entries[index].update(changes)
    return entries


def mutate_adjustment(index=0, **changes):
    entries = copy.deepcopy(BASE_ENTRIES)
    adjustment = entries[index].get("structured_adjustment") or {}
    adjustment.update(changes)
    entries[index]["structured_adjustment"] = adjustment
    return entries


def expect_reject(request, raw):
    with pytest.raises(GridWiseError) as excinfo:
        validate(request, raw)
    assert excinfo.value.category is ErrorCategory.invalid_interpretation
    return excinfo.value


# --- happy paths -------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_all_public_reference_interpretations_pass(case):
    request = EnergyRequest(**case["input"])
    directives = validate(request, envelope(STUB_INTERP[case["id"]]))
    assert len(directives) == len(request.operator_notes)
    assert [d.note_index for d in directives] == list(range(len(directives)))


def test_bare_array_envelope_is_tolerated():
    assert validate(BASE_REQUEST, copy.deepcopy(BASE_ENTRIES))


def test_unordered_hours_are_normalised_not_rejected():
    entries = mutate_adjustment(hours=[13, 12])
    directives = validate(BASE_REQUEST, envelope(entries))
    assert directives[0].structured_adjustment.hours == [12, 13]


# --- envelope and arity ------------------------------------------------------


def test_missing_directive_interpretation_key():
    expect_reject(BASE_REQUEST, {"reasoning": "only scratch"})


def test_raw_is_not_object_or_array():
    expect_reject(BASE_REQUEST, "a plain string")


def test_directive_interpretation_not_an_array():
    expect_reject(BASE_REQUEST, {"directive_interpretation": {"note_index": 0}})


def test_too_few_entries():
    expect_reject(BASE_REQUEST, envelope(BASE_ENTRIES[:1]))


def test_too_many_entries():
    expect_reject(BASE_REQUEST, envelope(BASE_ENTRIES + [copy.deepcopy(BASE_ENTRIES[1])]))


def test_entry_is_not_an_object():
    expect_reject(BASE_REQUEST, envelope(["not-an-object", BASE_ENTRIES[1]]))


# --- hours -------------------------------------------------------------------


def test_duplicate_hours_rejected():
    expect_reject(BASE_REQUEST, envelope(mutate_adjustment(hours=[12, 12, 13])))


def test_hour_above_range_rejected():
    expect_reject(BASE_REQUEST, envelope(mutate_adjustment(hours=[23, 24])))


def test_negative_hour_rejected():
    expect_reject(BASE_REQUEST, envelope(mutate_adjustment(hours=[-1, 5])))


def test_boolean_masquerading_as_hour_rejected():
    expect_reject(BASE_REQUEST, envelope(mutate_adjustment(hours=[True, 5])))


def test_empty_hours_rejected():
    expect_reject(BASE_REQUEST, envelope(mutate_adjustment(hours=[])))


def test_hours_not_a_list_rejected():
    expect_reject(BASE_REQUEST, envelope(mutate_adjustment(hours=12)))


def test_float_hour_rejected():
    expect_reject(BASE_REQUEST, envelope(mutate_adjustment(hours=[12.5, 13])))


# --- applies semantics -------------------------------------------------------


def test_no_op_with_applies_true_rejected():
    expect_reject(BASE_REQUEST, envelope(mutate(index=1, applies=True)))


def test_no_op_with_non_null_adjustment_rejected():
    entries = mutate(index=1, structured_adjustment={"hours": [1]})
    expect_reject(BASE_REQUEST, envelope(entries))


def test_real_directive_with_applies_false_rejected():
    expect_reject(BASE_REQUEST, envelope(mutate(index=0, applies=False)))


def test_unknown_directive_type_rejected():
    expect_reject(BASE_REQUEST, envelope(mutate(index=0, directive_type="curtail_everything")))


# --- numeric values ----------------------------------------------------------


def test_solar_reduction_missing_factor_rejected():
    entries = copy.deepcopy(BASE_ENTRIES)
    entries[0]["structured_adjustment"] = {"hours": [12, 13]}
    expect_reject(BASE_REQUEST, envelope(entries))


def test_factor_above_one_rejected():
    expect_reject(BASE_REQUEST, envelope(mutate_adjustment(factor=1.5)))


def test_negative_factor_rejected():
    expect_reject(BASE_REQUEST, envelope(mutate_adjustment(factor=-0.1)))


def test_boolean_factor_rejected():
    expect_reject(BASE_REQUEST, envelope(mutate_adjustment(factor=True)))


def test_string_factor_rejected():
    expect_reject(BASE_REQUEST, envelope(mutate_adjustment(factor="0.25")))


def test_extra_key_in_adjustment_rejected():
    expect_reject(BASE_REQUEST, envelope(mutate_adjustment(curtail=True)))


def test_reserve_above_battery_capacity_rejected():
    case = next(c for c in CASES if c["id"] == "SAMPLE-03")
    request = EnergyRequest(**case["input"])
    entries = copy.deepcopy(STUB_INTERP["SAMPLE-03"])
    target = next(e for e in entries if e["directive_type"] == "minimum_battery_reserve")
    target["structured_adjustment"]["minimum_energy_kwh"] = request.battery.capacity_kwh + 1
    expect_reject(request, envelope(entries))


def test_negative_reserve_rejected():
    case = next(c for c in CASES if c["id"] == "SAMPLE-03")
    request = EnergyRequest(**case["input"])
    entries = copy.deepcopy(STUB_INTERP["SAMPLE-03"])
    target = next(e for e in entries if e["directive_type"] == "minimum_battery_reserve")
    target["structured_adjustment"]["minimum_energy_kwh"] = -5
    expect_reject(request, envelope(entries))


def test_negative_grid_cap_rejected():
    case = next(c for c in CASES if c["id"] == "SAMPLE-05")
    request = EnergyRequest(**case["input"])
    entries = copy.deepcopy(STUB_INTERP["SAMPLE-05"])
    target = next(e for e in entries if e["directive_type"] == "max_grid_window")
    target["structured_adjustment"]["max_grid_kwh"] = -1
    expect_reject(request, envelope(entries))


# --- note mapping ------------------------------------------------------------


def test_duplicate_note_index_rejected():
    expect_reject(BASE_REQUEST, envelope(mutate(index=1, note_index=0)))


def test_note_index_gap_rejected():
    expect_reject(BASE_REQUEST, envelope(mutate(index=1, note_index=5)))


def test_out_of_order_note_index_rejected():
    entries = copy.deepcopy(BASE_ENTRIES)
    entries.reverse()
    expect_reject(BASE_REQUEST, envelope(entries))


# --- security ----------------------------------------------------------------


def test_rejection_messages_never_echo_operator_note_text():
    """Notes are untrusted input; a rejection must not replay them downstream."""
    error = expect_reject(BASE_REQUEST, envelope(mutate_adjustment(factor=1.5)))
    for note in BASE_REQUEST.operator_notes:
        for word in note.split():
            if len(word) > 6:
                assert word.lower() not in error.message.lower()


# --- strict-schema envelope artefacts ---------------------------------------


def test_null_magnitudes_from_strict_schema_are_stripped():
    """Strict mode forces all magnitudes to be present; nulls must not reject."""
    entries = mutate_adjustment(minimum_energy_kwh=None, max_grid_kwh=None)
    directives = validate(BASE_REQUEST, envelope(entries))
    assert directives[0].structured_adjustment.factor == 0.25


def test_non_null_wrong_magnitude_is_still_rejected():
    """A real value under the wrong key means the model was confused."""
    expect_reject(BASE_REQUEST, envelope(mutate_adjustment(minimum_energy_kwh=120)))


def test_null_own_magnitude_is_rejected_not_defaulted():
    expect_reject(BASE_REQUEST, envelope(mutate_adjustment(factor=None)))

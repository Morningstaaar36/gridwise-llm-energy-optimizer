"""Deterministic validation of model output.

The model's structured output is untrusted data until it passes through here.
``app.contracts`` owns the *shape* rules (discriminated union, enum membership,
``applies`` semantics, hour ranges); this module owns the rules that need the
request in hand, plus the safe normalisations the specification allows.

Two rules drive every decision below:

* **Never repair by guessing.** A missing or nonsensical value is rejected so
  the bounded repair round can re-ask. Substituting a default would turn a
  model error into a confidently wrong schedule, which scores worse than a
  controlled failure.
* **Never echo note text.** Violation messages name note *indexes* only.
  Operator notes are untrusted input and must not reach logs or responses.
"""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter, ValidationError

from app.contracts import Directive, EnergyRequest, ErrorCategory, GridWiseError

_DIRECTIVE_LIST = TypeAdapter(list[Directive])

# Adjustment keys that carry a magnitude, by directive type. Used only to give
# a precise rejection reason; the authoritative shape check is the union.
_MAGNITUDE_KEY = {
    "solar_reduction": "factor",
    "minimum_battery_reserve": "minimum_energy_kwh",
    "max_grid_window": "max_grid_kwh",
}


def _reject(message: str) -> GridWiseError:
    return GridWiseError(ErrorCategory.invalid_interpretation, message)


def extract_entries(raw: Any) -> list[Any]:
    """Pull the directive array out of whatever envelope the model returned."""
    if isinstance(raw, dict):
        if "directive_interpretation" not in raw:
            raise _reject("model output is missing 'directive_interpretation'")
        entries = raw["directive_interpretation"]
    elif isinstance(raw, list):
        entries = raw  # tolerate a bare array
    else:
        raise _reject("model output is not a JSON object or array")

    if not isinstance(entries, list):
        raise _reject("'directive_interpretation' is not an array")
    return entries


def _normalise_explanation(entry: dict[str, Any]) -> None:
    """Accept a per-entry ``reasoning`` field as the entry's ``explanation``.

    Models reliably drift on where free-text goes, and the specification states
    that explanation wording is not matched byte-for-byte. Supplying or renaming
    a cosmetic field is therefore safe — unlike hours, factors, or reserves,
    which are scored and are never defaulted.
    """
    if "reasoning" in entry and "explanation" not in entry:
        value = entry.pop("reasoning")
        if isinstance(value, str) and value.strip():
            entry["explanation"] = value[:300]
    entry.pop("reasoning", None)
    explanation = entry.get("explanation")
    if not isinstance(explanation, str) or not explanation.strip():
        entry["explanation"] = "Interpretation of the operator note."


def _strip_null_magnitudes(entry: dict[str, Any]) -> None:
    """Drop magnitude keys that are explicitly null and belong to another type.

    Strict structured-output mode cannot express "required only for this
    directive type", so the schema marks every magnitude nullable and models
    dutifully emit all three with nulls for the irrelevant ones. Removing an
    explicit ``null`` invents nothing — there is no value being guessed. A
    *non-null* value under the wrong key still fails, because that signals the
    model was confused about the directive, not merely about the envelope.
    """
    adjustment = entry.get("structured_adjustment")
    if not isinstance(adjustment, dict):
        return
    keep = _MAGNITUDE_KEY.get(entry.get("directive_type"))  # type: ignore[arg-type]
    for key in ("factor", "minimum_energy_kwh", "max_grid_kwh"):
        if key != keep and adjustment.get(key, ...) is None:
            adjustment.pop(key)


def _normalise_hours(entry: dict[str, Any], index: int) -> None:
    """Sort merely-unordered hours in place; reject anything genuinely wrong.

    The specification requires ascending unique hours 0-23. Ordering carries no
    meaning, so re-ordering is a safe normalisation. Duplicates and out-of-range
    values are *not* safe to fix, because either could mean the model
    misidentified the window.
    """
    adjustment = entry.get("structured_adjustment")
    if not isinstance(adjustment, dict) or "hours" not in adjustment:
        return

    hours = adjustment["hours"]
    if not isinstance(hours, list) or not hours:
        raise _reject(f"note {index}: 'hours' must be a non-empty array")

    for hour in hours:
        # bool is a subclass of int; a JSON `true` must never become hour 1.
        if isinstance(hour, bool) or not isinstance(hour, int):
            raise _reject(f"note {index}: 'hours' must contain integers")
        if not 0 <= hour <= 23:
            raise _reject(f"note {index}: hour {hour} is outside 0-23")

    if len(set(hours)) != len(hours):
        raise _reject(f"note {index}: 'hours' contains duplicates")

    adjustment["hours"] = sorted(hours)


def _check_magnitude_present(entry: dict[str, Any], index: int) -> None:
    """Give a precise reason before the union reports a generic shape error."""
    directive_type = entry.get("directive_type")
    key = _MAGNITUDE_KEY.get(directive_type)  # type: ignore[arg-type]
    if key is None:
        return
    adjustment = entry.get("structured_adjustment")
    if not isinstance(adjustment, dict) or key not in adjustment:
        raise _reject(f"note {index}: {directive_type} requires '{key}'")
    value = adjustment[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _reject(f"note {index}: '{key}' must be a number")


def validate(request: EnergyRequest, raw: Any) -> list[Directive]:
    """Return typed directives, or raise ``GridWiseError`` with a safe message."""
    entries = extract_entries(raw)
    expected = len(request.operator_notes)

    if len(entries) != expected:
        raise _reject(
            f"expected exactly {expected} directive entries, received {len(entries)}"
        )

    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise _reject(f"entry {position} is not an object")
        _normalise_explanation(entry)
        _strip_null_magnitudes(entry)
        _normalise_hours(entry, position)
        _check_magnitude_present(entry, position)

    try:
        directives = _DIRECTIVE_LIST.validate_python(entries)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ()) if part != "function-after")
        raise _reject(f"invalid directive at {location or 'root'}: {first.get('msg', 'schema error')}")

    _check_note_mapping(directives, expected)
    _check_against_battery(request, directives)
    return directives


def _check_note_mapping(directives: list[Directive], expected: int) -> None:
    """One entry per note, each exactly once, in ascending note_index order."""
    indexes = [directive.note_index for directive in directives]
    if sorted(indexes) != list(range(expected)):
        raise _reject(
            f"note_index values must be exactly 0..{expected - 1} with no gaps or duplicates"
        )
    if indexes != sorted(indexes):
        raise _reject("directive entries must be returned in ascending note_index order")


def _check_against_battery(request: EnergyRequest, directives: list[Directive]) -> None:
    """Request-relative bounds the schema alone cannot know."""
    capacity = request.battery.capacity_kwh
    for directive in directives:
        adjustment = directive.structured_adjustment
        reserve = getattr(adjustment, "minimum_energy_kwh", None)
        if reserve is not None and reserve > capacity:
            raise _reject(
                f"note {directive.note_index}: reserve {reserve} kWh exceeds "
                f"battery capacity {capacity} kWh"
            )

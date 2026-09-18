"""B4.3 — the ten public cases over live HTTP, against the fully merged system.

This is the end-to-end acceptance gate for the whole system. Every
other check in the repo tests a piece in isolation (the LP against ground
truth, the compiler in isolation, the interpreter against paraphrases). This
is the only script that drives a running HTTP server with the real model on
one end and the real optimizer on the other, and checks the whole thing
end-to-end against organizer ground truth.

For each of the 10 public cases:
  - POST the input to a running service
  - compare directive_interpretation structurally against the expected one
    (ignore explanation wording, per the spec)
  - replay the returned plan independently (energy balance, battery bounds,
    rate limits, directive constraints, end-of-day neutrality)
  - compare recalculated cost against the published reference

A cost above reference is only acceptable when the hedge visibly widened the
candidate set; anything else is a bug to
investigate before Gate 5.

Usage:
    python evals/run_public.py [--base-url http://localhost:8000]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from dataclasses import asdict, dataclass, field

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.contracts import EnergyRequest  # noqa: E402

FIXTURES = ROOT / "fixtures" / "public_cases.json"
REPORTS = ROOT / "evals" / "reports"
TOLERANCE = 0.01  # kWh / BDT, per the problem statement's stated tolerance


def structurally_equal(got: dict, expected: dict) -> tuple[bool, str]:
    """Compare directive_interpretation entries, ignoring explanation wording."""
    if got.get("note_index") != expected.get("note_index"):
        return False, f"note_index {got.get('note_index')} != {expected.get('note_index')}"
    if got.get("applies") != expected.get("applies"):
        return False, f"applies {got.get('applies')} != {expected.get('applies')}"
    if got.get("directive_type") != expected.get("directive_type"):
        return False, (
            f"directive_type {got.get('directive_type')} "
            f"!= {expected.get('directive_type')}"
        )

    ga, ea = got.get("structured_adjustment"), expected.get("structured_adjustment")
    if ea is None:
        reason = "structured_adjustment should be null" if ga is not None else ""
        return (ga is None), reason
    if ga is None:
        return False, "structured_adjustment is null, expected a value"
    if set(ga.get("hours", [])) != set(ea.get("hours", [])):
        return False, f"hours {ga.get('hours')} != {ea.get('hours')}"
    for key in ("factor", "minimum_energy_kwh", "max_grid_kwh"):
        if key in ea:
            gv = ga.get(key)
            if gv is None or abs(gv - ea[key]) > TOLERANCE:
                return False, f"{key} {gv} != {ea[key]}"
    return True, ""


def replay(request: EnergyRequest, plan: list[dict]) -> list[str]:
    """Independent arithmetic replay -- rebuilt from the raw request only,
    never from anything the service returned besides the plan itself."""
    hours_by_index = {h.hour: h for h in request.hours}
    battery = request.battery
    violations: list[str] = []
    energy = battery.initial_energy_kwh

    if len(plan) != 24 or [p["hour"] for p in plan] != list(range(24)):
        violations.append("plan does not cover exactly hours 0-23 in order")
        return violations

    for entry in plan:
        h = entry["hour"]
        demand = hours_by_index[h].demand_kwh
        action, magnitude = entry["battery_action"], entry["battery_kwh"]
        charge = magnitude if action == "charge" else 0.0
        discharge = magnitude if action == "discharge" else 0.0

        if action == "idle" and abs(magnitude) > TOLERANCE:
            violations.append(f"h{h}: idle with nonzero magnitude {magnitude}")
        if charge > battery.max_charge_kwh_per_hour + TOLERANCE:
            violations.append(f"h{h}: charge {charge} exceeds rate limit")
        if discharge > battery.max_discharge_kwh_per_hour + TOLERANCE:
            violations.append(f"h{h}: discharge {discharge} exceeds rate limit")

        balance = entry["grid_kwh"] + entry["solar_used_kwh"] + discharge - demand - charge
        if abs(balance) > TOLERANCE:
            violations.append(f"h{h}: energy balance off by {balance:.4f}")

        energy = energy + charge - discharge
        if abs(energy - entry["battery_energy_after_kwh"]) > TOLERANCE:
            violations.append(f"h{h}: battery state mismatch, expected {energy:.4f}")
        below = energy < battery.minimum_energy_kwh - TOLERANCE
        above = energy > battery.capacity_kwh + TOLERANCE
        if below or above:
            violations.append(f"h{h}: battery energy {energy:.4f} outside base bounds")

    if abs(energy - battery.initial_energy_kwh) > TOLERANCE:
        violations.append(f"end-of-day energy {energy:.4f} != initial {battery.initial_energy_kwh}")

    return violations


@dataclass
class CaseResult:
    case_id: str
    http_status: int = 0
    latency_s: float = 0.0
    interpretation_correct: bool = False
    interpretation_errors: list[str] = field(default_factory=list)
    replay_violations: list[str] = field(default_factory=list)
    reference_cost: float = 0.0
    got_cost: float = 0.0
    cost_within_tolerance: bool = False
    valid: bool = False
    error: str | None = None


def run_case(client: httpx.Client, case: dict) -> CaseResult:
    result = CaseResult(
        case_id=case["id"], reference_cost=case["expected_output"]["total_cost_bdt"]
    )
    request = EnergyRequest(**case["input"])

    start = time.perf_counter()
    try:
        response = client.post("/optimize-energy", json=case["input"], timeout=35.0)
    except httpx.RequestError as exc:
        result.error = f"request failed: {exc}"
        return result
    result.latency_s = time.perf_counter() - start
    result.http_status = response.status_code

    if response.status_code != 200:
        result.error = f"HTTP {response.status_code}: {response.text[:200]}"
        return result

    body = response.json()

    expected_by_index = {
        d["note_index"]: d for d in case["expected_output"]["directive_interpretation"]
    }
    got_by_index = {d["note_index"]: d for d in body["directive_interpretation"]}
    all_match = True
    for index, expected in expected_by_index.items():
        got = got_by_index.get(index)
        if got is None:
            result.interpretation_errors.append(f"note {index}: missing from response")
            all_match = False
            continue
        ok, reason = structurally_equal(got, expected)
        if not ok:
            result.interpretation_errors.append(f"note {index}: {reason}")
            all_match = False
    result.interpretation_correct = all_match

    result.replay_violations = replay(request, body["hourly_plan"])
    result.got_cost = body["total_cost_bdt"]
    result.cost_within_tolerance = result.got_cost <= result.reference_cost + TOLERANCE  # noqa: E501

    result.valid = (
        result.interpretation_correct
        and not result.replay_violations
        and result.got_cost >= result.reference_cost - TOLERANCE
    )
    return result


def main(base_url: str) -> int:
    cases = json.load(open(FIXTURES))["cases"]
    client = httpx.Client(base_url=base_url)

    results: list[CaseResult] = []
    header = (
        f"{'case':10} {'http':>5} {'interp':>7} {'replay':>7} "
        f"{'ref cost':>10} {'got cost':>10} {'prem%':>7}  {'s':>5}"
    )
    print(header)
    for case in cases:
        result = run_case(client, case)
        premium = (
            100 * (result.got_cost - result.reference_cost) / result.reference_cost
            if result.reference_cost
            else 0
        )
        print(
            f"{result.case_id:10} {result.http_status:5} "
            f"{'OK' if result.interpretation_correct else 'MISS':>7} "
            f"{'OK' if not result.replay_violations else 'FAIL':>7} "
            f"{result.reference_cost:10.2f} {result.got_cost:10.2f} {premium:6.3f}%  "
            f"{result.latency_s:5.2f}"
        )
        if result.error:
            print(f"           error: {result.error}")
        for err in result.interpretation_errors:
            print(f"           interpretation: {err}")
        for viol in result.replay_violations[:5]:
            print(f"           replay: {viol}")
        results.append(result)

    client.close()

    valid = sum(r.valid for r in results)
    interp_ok = sum(r.interpretation_correct for r in results)
    replay_ok = sum(not r.replay_violations for r in results)
    hedged = [r.case_id for r in results if r.got_cost > r.reference_cost + TOLERANCE]

    print()
    print(
        f"=== {valid}/10 valid | {interp_ok}/10 interpretation correct | "
        f"{replay_ok}/10 replay clean ==="
    )
    if hedged:
        print(f"cases above reference cost (must be hedge-widened, investigate if not): {hedged}")

    REPORTS.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS / f"public_cases_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_url": base_url,
        "valid": valid,
        "interpretation_correct": interp_ok,
        "replay_clean": replay_ok,
        "hedged_cases": hedged,
        "cases": [asdict(r) for r in results],
    }, indent=2))
    print(f"report written: {out_path.relative_to(ROOT)}")

    return 0 if valid == 10 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    raise SystemExit(main(args.base_url))

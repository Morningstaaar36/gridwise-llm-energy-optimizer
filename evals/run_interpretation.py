"""S3.2 — live interpretation eval against paraphrased operator notes.

Runs every line of ``fixtures/paraphrase_clusters.jsonl`` through the real
model and reports exact structured match rate, per-directive-type failures,
within-cluster agreement (paraphrase robustness), invalid-output rate, and
p50/p95 latency.

Deliberately uses K=1 per note: this eval validates *prompt quality* across
unseen phrasings, not the K-sample hedge (that lives in app/energy/canonical.py,
Daddy's D3.1). Testing at K=1 keeps this fast and avoids amplifying provider
rate-limit pressure 5x for a question K=1 already answers.

Each fixture line is a single note with no scenario context, so a fixed
synthetic 24-hour scenario carries it -- large enough (capacity 300 kWh) to
accept the 120 kWh reserve case without tripping the capacity guardrail.
Demand/solar/tariff values are plausible but arbitrary; this script never
calls the optimizer.

Usage:
    python evals/run_interpretation.py [--k N] [--base-url URL]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import statistics
import sys
import time
from dataclasses import asdict, dataclass

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.contracts import Battery, EnergyRequest, GridWiseError, HourEntry  # noqa: E402
from app.interpretation.ensemble import interpret_notes  # noqa: E402
from app.interpretation.provider import LLMProvider  # noqa: E402
from app.observability import RequestTrace, configure_logging  # noqa: E402

FIXTURES = ROOT / "fixtures" / "paraphrase_clusters.jsonl"
REPORTS = ROOT / "evals" / "reports"

_HOURS = [
    HourEntry(
        hour=h,
        demand_kwh=100 + 5 * h,
        solar_kwh=max(0, 150 - abs(h - 13) * 15),
        tariff_bdt_per_kwh=8 + (h % 6),
    )
    for h in range(24)
]
_BATTERY = Battery(
    capacity_kwh=300,
    initial_energy_kwh=150,
    minimum_energy_kwh=30,
    max_charge_kwh_per_hour=80,
    max_discharge_kwh_per_hour=80,
)


def synthetic_request(note: str, scenario_id: str) -> EnergyRequest:
    return EnergyRequest(
        scenario_id=scenario_id, operator_notes=[note], hours=_HOURS, battery=_BATTERY
    )


@dataclass
class CaseResult:
    cluster_id: int
    phrasing_id: int
    note: str
    expected_type: str
    expected_applies: bool
    expected_adjustment: dict | None
    got_type: str | None = None
    got_applies: bool | None = None
    got_adjustment: dict | None = None
    exact_match: bool = False
    invalid: bool = False
    error: str | None = None
    latency_s: float = 0.0


def matches(result: CaseResult) -> bool:
    if (
        result.invalid
        or result.got_type != result.expected_type
        or result.got_applies != result.expected_applies
    ):
        return False
    if result.expected_adjustment is None:
        return result.got_adjustment is None
    if result.got_adjustment is None:
        return False
    # Hours must match as sets (ordering is a guardrail concern, already enforced);
    # numeric fields compared with the spec's 0.01 tolerance.
    exp, got = result.expected_adjustment, result.got_adjustment
    if set(exp.get("hours", [])) != set(got.get("hours", [])):
        return False
    for key in ("factor", "minimum_energy_kwh", "max_grid_kwh"):
        if key in exp:
            if key not in got or abs(exp[key] - got[key]) > 0.01:
                return False
    return True


async def run_case(provider: LLMProvider, settings, line: dict, index: int) -> CaseResult:
    result = CaseResult(
        cluster_id=line["cluster_id"],
        phrasing_id=line["phrasing_id"],
        note=line["note"],
        expected_type=line["expected_directive_type"],
        expected_applies=line["expected_applies"],
        expected_adjustment=line["expected_structured_adjustment"],
    )
    request = synthetic_request(line["note"], f"PARAPHRASE-{index:02d}")
    start = time.perf_counter()
    try:
        samples = await interpret_notes(request, settings, provider, RequestTrace())
        result.latency_s = time.perf_counter() - start
        directive = samples[0].directives[0]
        result.got_type = directive.directive_type.value
        result.got_applies = directive.applies
        adjustment = directive.structured_adjustment
        result.got_adjustment = adjustment.model_dump() if adjustment else None
    except GridWiseError as exc:
        result.latency_s = time.perf_counter() - start
        result.invalid = True
        result.error = f"{exc.category.value}: {exc.message}"
    result.exact_match = matches(result)
    return result


async def main(k: int, base_url: str | None) -> int:
    configure_logging("WARNING")
    settings = get_settings()
    if k != settings.llm_samples:
        settings = settings.model_copy(update={"llm_samples": k})
    if base_url:
        settings = settings.model_copy(update={"llm_base_url": base_url})

    lines = [json.loads(line) for line in FIXTURES.read_text().splitlines() if line.strip()]
    provider = LLMProvider(settings)

    results: list[CaseResult] = []
    for index, line in enumerate(lines):
        result = await run_case(provider, settings, line, index)
        status = "OK " if result.exact_match else ("INVALID" if result.invalid else "MISS")
        print(f"[{status}] cluster {result.cluster_id} phrasing {result.phrasing_id} "
              f"({result.latency_s:.2f}s): {result.note[:60]}")
        if not result.exact_match and not result.invalid:
            print(f"         expected {result.expected_type} {result.expected_adjustment}")
            print(f"         got      {result.got_type} {result.got_adjustment}")
        results.append(result)
        await asyncio.sleep(0.5)  # stay clear of RPM bursts between sequential calls

    await provider.aclose()

    exact = sum(r.exact_match for r in results)
    invalid = sum(r.invalid for r in results)
    latencies = sorted(r.latency_s for r in results if not r.invalid)

    by_type: dict[str, list[bool]] = {}
    for r in results:
        by_type.setdefault(r.expected_type, []).append(r.exact_match)

    by_cluster: dict[int, list[bool]] = {}
    for r in results:
        by_cluster.setdefault(r.cluster_id, []).append(r.exact_match)
    cluster_agreement = {
        cid: sum(matches_) / len(matches_) for cid, matches_ in by_cluster.items()
    }

    def pct(values: list[float], p: float) -> float:
        if not values:
            return 0.0
        idx = min(len(values) - 1, int(len(values) * p))
        return round(values[idx], 3)

    summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": settings.llm_model,
        "k": k,
        "total_cases": len(results),
        "exact_matches": exact,
        "exact_match_rate": round(exact / len(results), 3),
        "invalid_output_count": invalid,
        "invalid_output_rate": round(invalid / len(results), 3),
        "per_directive_type": {
            t: {"n": len(v), "exact": sum(v), "rate": round(sum(v) / len(v), 3)}
            for t, v in by_type.items()
        },
        "per_cluster_agreement": cluster_agreement,
        "mean_cluster_agreement": (
            round(statistics.mean(cluster_agreement.values()), 3) if cluster_agreement else 0.0
        ),
        "latency_p50_s": pct(latencies, 0.50),
        "latency_p95_s": pct(latencies, 0.95),
        "cases": [asdict(r) for r in results],
    }

    REPORTS.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS / f"interpretation_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(summary, indent=2))

    print()
    print(f"=== {exact}/{len(results)} exact match ({summary['exact_match_rate']*100:.0f}%), "
          f"{invalid} invalid, p50={summary['latency_p50_s']}s p95={summary['latency_p95_s']}s ===")
    print(f"mean within-cluster agreement: {summary['mean_cluster_agreement']*100:.0f}%")
    print(f"report written: {out_path.relative_to(ROOT)}")

    return 0 if exact >= 18 else 1  # acceptance gate: >=18/20 exact on the seed clusters


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--k", type=int, default=1,
        help="samples per note (default 1: tests the prompt, not the hedge)",
    )
    parser.add_argument("--base-url", default=None, help="override LLM_BASE_URL for this run")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.k, args.base_url)))

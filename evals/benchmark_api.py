"""S5.1 — latency measurement and provider failure injection.

Two independent halves, because they have very different costs:

* ``--latency`` drives a **running server** with real model calls. Defaults are
  deliberately small: the free-tier providers throttle hard, and burning quota
  here would leave nothing for the deployment gate. The scored target is
  p95 <= 5s (3/3 latency points); >5-15s scores 2/3.
* ``--failures`` runs **entirely in-process with no network at all**. Failures
  are injected at the provider adapter (``LLMProvider._one_call``) so the real
  retry, fallback, repair-round, and guardrail logic all execute and the
  attempt budget can actually be counted.

There is no interpretation cache in this system (it was scoped as optional and
never built), so the spec's "with the cache disabled" is satisfied by
construction rather than by a flag.

Usage:
    python evals/benchmark_api.py --base-url http://localhost:8000
    python evals/benchmark_api.py --failures-only        # no network, no quota
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
import time
from dataclasses import asdict, dataclass, field

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / "fixtures" / "public_cases.json"
REPORTS = ROOT / "evals" / "reports"
CASES = json.loads(FIXTURES.read_text())["cases"]


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return round(ordered[index], 3)


# --- latency (live) ----------------------------------------------------------


@dataclass
class LatencySection:
    cold_s: float = 0.0
    sequential: list[float] = field(default_factory=list)
    concurrent: list[float] = field(default_factory=list)
    non_200: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        warm = self.sequential + self.concurrent
        return {
            "cold_first_request_s": round(self.cold_s, 3),
            "sequential_n": len(self.sequential),
            "sequential_p50_s": percentile(self.sequential, 0.50),
            "sequential_p95_s": percentile(self.sequential, 0.95),
            "concurrent_n": len(self.concurrent),
            "concurrent_p50_s": percentile(self.concurrent, 0.50),
            "concurrent_p95_s": percentile(self.concurrent, 0.95),
            "overall_warm_p50_s": percentile(warm, 0.50),
            "overall_warm_p95_s": percentile(warm, 0.95),
            "non_200_responses": self.non_200,
        }


def run_latency(base_url: str, requests: int, concurrency: int) -> LatencySection:
    section = LatencySection()
    payloads = [CASES[i % len(CASES)]["input"] for i in range(requests)]

    with httpx.Client(base_url=base_url, timeout=40.0) as client:
        start = time.perf_counter()
        first = client.post("/optimize-energy", json=payloads[0])
        section.cold_s = time.perf_counter() - start
        if first.status_code != 200:
            section.non_200.append(f"cold: HTTP {first.status_code}")
        print(f"  cold first request: {section.cold_s:.2f}s (HTTP {first.status_code})")

        for index, payload in enumerate(payloads[1:], start=2):
            begin = time.perf_counter()
            response = client.post("/optimize-energy", json=payload)
            elapsed = time.perf_counter() - begin
            section.sequential.append(elapsed)
            if response.status_code != 200:
                section.non_200.append(f"sequential {index}: HTTP {response.status_code}")
            print(f"  sequential {index}: {elapsed:.2f}s (HTTP {response.status_code})")

    async def concurrent_burst() -> None:
        async with httpx.AsyncClient(base_url=base_url, timeout=40.0) as client:

            async def one(payload: dict) -> tuple[float, int]:
                begin = time.perf_counter()
                response = await client.post("/optimize-energy", json=payload)
                return time.perf_counter() - begin, response.status_code

            results = await asyncio.gather(
                *(one(CASES[i % len(CASES)]["input"]) for i in range(concurrency))
            )
            for position, (elapsed, status) in enumerate(results, start=1):
                section.concurrent.append(elapsed)
                if status != 200:
                    section.non_200.append(f"concurrent {position}: HTTP {status}")
                print(f"  concurrent {position}: {elapsed:.2f}s (HTTP {status})")

    print(f"  --- {concurrency} concurrent ---")
    asyncio.run(concurrent_burst())
    return section


# --- failure injection (hermetic, no network) --------------------------------


@dataclass
class InjectionResult:
    scenario: str
    http_status: int
    error_category: str
    provider_calls: int
    body_is_controlled: bool
    leaked_secret: bool
    service_still_up: bool


def run_failure_injection() -> list[InjectionResult]:
    """Inject at LLMProvider._one_call so the real retry/repair logic executes."""
    import httpx as _httpx
    from fastapi.testclient import TestClient
    from openai import APITimeoutError, AuthenticationError, RateLimitError

    from app.config import get_settings
    from app.interpretation.provider import LLMProvider

    settings = get_settings()
    secret = settings.llm_api_key
    case = CASES[0]["input"]
    results: list[InjectionResult] = []

    def openai_error(cls, status: int, message: str):
        body = {"error": {"message": message}}
        response = _httpx.Response(
            status, request=_httpx.Request("POST", "http://x"), json=body
        )
        return cls(message, response=response, body=body)

    scenarios: dict[str, object] = {
        # Provider answers, but with text guardrails must reject. Exercises the
        # repair round, then a controlled invalid_interpretation.
        "malformed_json": "not json at all, just prose",
        "timeout": APITimeoutError(request=_httpx.Request("POST", "http://x")),
        "auth_401": openai_error(AuthenticationError, 401, "invalid api key provided"),
        "rate_limit_429": openai_error(RateLimitError, 429, "rate limit reached"),
        "full_outage": RuntimeError("connection refused"),
    }

    for name, behaviour in scenarios.items():
        calls = {"n": 0}

        async def fake_one_call(self, endpoint, prompt, n, _behaviour=behaviour, _calls=calls):
            _calls["n"] += 1
            if isinstance(_behaviour, BaseException):
                raise _behaviour
            return [_behaviour] * max(1, n)

        original = LLMProvider._one_call
        LLMProvider._one_call = fake_one_call
        try:
            from app.main import app

            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post("/optimize-energy", json=case)
                text = response.text
                health = client.get("/health")
        finally:
            LLMProvider._one_call = original

        try:
            payload = response.json()
            controlled = isinstance(payload, dict) and "error" in payload and "detail" in payload
            category = payload.get("error", "")
        except Exception:
            controlled = False
            category = ""

        results.append(
            InjectionResult(
                scenario=name,
                http_status=response.status_code,
                error_category=category,
                provider_calls=calls["n"],
                body_is_controlled=controlled,
                leaked_secret=bool(secret) and secret in text,
                service_still_up=health.status_code == 200,
            )
        )
        print(
            f"  {name:16} HTTP {response.status_code} "
            f"category={category:24} provider_calls={calls['n']:2} "
            f"controlled={controlled} leak={results[-1].leaked_secret} "
            f"up={results[-1].service_still_up}"
        )

    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=5, help="sequential live requests")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--failures-only", action="store_true", help="no network, no quota")
    parser.add_argument("--latency-only", action="store_true")
    args = parser.parse_args()

    report: dict = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    ok = True

    if not args.failures_only:
        print("=== latency (live model) ===")
        section = run_latency(args.base_url, args.requests, args.concurrency)
        report["latency"] = section.summary()
        p95 = report["latency"]["overall_warm_p95_s"]
        band = "3/3" if p95 <= 5 else "2/3" if p95 <= 15 else "1/3" if p95 <= 30 else "0/3"
        report["latency"]["scored_band"] = band
        print(f"\n  warm p50={report['latency']['overall_warm_p50_s']}s "
              f"p95={p95}s -> latency points {band}")
        if section.non_200:
            ok = False
            print(f"  NON-200 RESPONSES: {section.non_200}")

    if not args.latency_only:
        print("\n=== provider failure injection (no network) ===")
        injections = run_failure_injection()
        report["failure_injection"] = [asdict(r) for r in injections]

        leaks = [r.scenario for r in injections if r.leaked_secret]
        uncontrolled = [r.scenario for r in injections if not r.body_is_controlled]
        down = [r.scenario for r in injections if not r.service_still_up]
        unbounded = [r.scenario for r in injections if r.provider_calls > 16]

        report["failure_injection_summary"] = {
            "secret_leaks": leaks,
            "uncontrolled_bodies": uncontrolled,
            "service_down_after": down,
            "unbounded_attempts": unbounded,
        }
        if leaks or uncontrolled or down or unbounded:
            ok = False
        print(
            f"\n  leaks={leaks or 'none'} uncontrolled={uncontrolled or 'none'} "
            f"down={down or 'none'} unbounded={unbounded or 'none'}"
        )

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"benchmark_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"\nreport written: {out.relative_to(ROOT)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

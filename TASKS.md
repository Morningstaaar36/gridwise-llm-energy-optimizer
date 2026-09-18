# GridWise — gated build plan

Round window **19:00–23:00**. Code freeze **21:30**. Follow this file top to bottom.

Environment setup is **not** in here — do [README.md](README.md) before the round opens.

**How to use this file.** Every task block below is a complete, self-contained agent prompt:
it names the files it may create, the files it may not touch, the stub it develops against, the
behaviour it must implement, and the exact command that proves it is done. Paste one block at a
time. Do not batch tasks across owners.

---

## 0. Ground rules

| Rule | Detail |
|---|---|
| **One owner per file** | No file appears in both owners' lists. This is what makes the Gate 4 merge trivial. |
| **`app/contracts.py` is frozen at Gate 1** | After Gate 1 neither branch edits it. A change needs both people to agree and lands on `main`, then both rebase. |
| **Everything under `schemas/` and `fixtures/` is read-only** | Created before branching. Never edited on a branch. |
| **Stub, never block** | If your module needs the other half, import the stub from `tests/stubs/`. You own your own stubs. |
| **No secrets anywhere** | Not in code, commits, logs, error bodies, prompts, the image, or the README. |
| **The LLM is mandatory in the interpretation path** | Regex/keyword matching as the sole interpreter fails the challenge outright. Stubs are for development only and must be gone from the request path by Gate 4. |
| **Commit small, push often** | `git push` at every task completion so the other person can see progress. |

### Branches

```
main                     scaffold, contracts, schemas, fixtures, docs
 ├── feat/lang-api       Siyam   (Linux, RTX 5060 Ti 16 GB)
 └── feat/energy-verify  Daddy   (macOS)
```

Both cut from `main` at Gate 1. Both merge back at Gate 4, Daddy first, then Siyam rebases.

### The single seam between the two branches

Exactly one type crosses the branch boundary. Everything else is private.

```
Siyam  →  interpret_notes(request) -> list[InterpretationSample]
Daddy  →  plan_energy(request, samples) -> (EnergyResponse, VerificationReport)
```

`pipeline.py` (Siyam) calls those two functions in order. That is the whole integration.

---

## 1. Folder and file layout

`O` column: **S** = Siyam, **D** = Daddy, **F** = frozen at Gate 1 / read-only, **M** = created on `main` before branching.

```text
gridwise-llm-energy-optimizer/
├── README.md                              M/D   env setup; D extends at Gate 7
├── TASKS.md                               M     this file; nobody edits during the round
├── environment.yml                        M
├── requirements.txt                       M
├── requirements-gpu.txt                   M     Linux+CUDA only, optional
├── requirements.lock.txt                  S     `make lock` output, committed at Gate 5
├── Dockerfile                             S
├── .dockerignore                          M
├── .env.example                           M
├── .gitignore                             M
├── pyproject.toml                         M
├── Makefile                               M
├── schemas/
│   ├── request.schema.json                F     inbound contract
│   ├── directive.schema.json              F     grammar-constrained decoding target
│   └── response.schema.json               F     outbound contract
├── fixtures/
│   ├── public_cases.json                  F     the 10 official cases
│   ├── stub_interpretation.json           F     ground-truth directives per case  -> Daddy's stub
│   ├── stub_llm_samples.json              F     5 canned samples w/ disagreement   -> Daddy's CS3 test
│   ├── stub_plan.json                     F     one canned valid 24 h plan         -> Siyam's stub
│   └── paraphrase_clusters.jsonl          F     4 clusters x 5 phrasings; D extends at Gate 3
├── app/
│   ├── __init__.py                        M
│   ├── contracts.py                       F     FROZEN at Gate 1 — the merge contract
│   ├── main.py                            S     FastAPI app, routes, exception handlers
│   ├── config.py                          S     env parsing (pydantic-settings)
│   ├── pipeline.py                        S     orchestration + request deadline
│   ├── observability.py                   S     stage timings, sanitised error categories
│   ├── interpretation/                    S
│   │   ├── provider.py                    S     OpenAI-protocol client, primary + fallback
│   │   ├── prompts.py                     S     versioned system prompt, spotlight delimiting
│   │   ├── ensemble.py                    S     ONE batched call -> K samples
│   │   └── guardrails.py                  S     deterministic validation of model output
│   ├── energy/                            D
│   │   ├── compiler.py                    D     directives -> ConstraintTensor
│   │   ├── canonical.py                   D     CS3: tensor-equality clustering -> posterior
│   │   ├── lattice.py                     D     meet, monotone-infeasibility pruning
│   │   ├── optimizer.py                   D     96-var signed-flow LP (HiGHS)
│   │   ├── selection.py                   D     expected-score rule, slack-maximal re-solve
│   │   ├── duals.py                       D     shadow-price attribution
│   │   └── response.py                    D     flows -> actions, totals, plan_summary
│   └── verification/                      D
│       └── replay.py                      D     independent arithmetic replay
├── tests/
│   ├── stubs/
│   │   ├── fake_energy.py                 S     canned EnergyResponse from stub_plan.json
│   │   └── fake_interpreter.py            D     samples from stub_interpretation/stub_llm_samples
│   ├── test_contracts.py                  S
│   ├── test_guardrails.py                 S
│   ├── test_ensemble.py                   S
│   ├── test_api.py                        S
│   ├── test_compiler.py                   D
│   ├── test_canonical.py                  D
│   ├── test_lattice.py                    D
│   ├── test_optimizer.py                  D
│   ├── test_selection.py                  D
│   ├── test_replay.py                     D
│   └── test_integration.py                M     written on main at Gate 4, both review
├── evals/
│   ├── verify_lp.py                       F     exists; LP vs 10 reference costs
│   ├── hedging_premium.py                 F     exists
│   ├── hedging_report.py                  F     exists
│   ├── run_public.py                      D     all 10 cases over HTTP
│   ├── run_interpretation.py              S     live-model paraphrase accuracy
│   ├── benchmark_api.py                   S     p50/p95, cold/warm, concurrency
│   └── reports/                           —     gitignored, evidence lands here
├── deploy/
│   ├── azure.md                           S     exact deploy commands + resource names
│   └── smoke.sh                           S     external /health + one sample
└── docs/
    ├── ARCHITECTURE_CLAMP.md              F     reference
    ├── RESEARCH_LINKS.md                  F     reference
    ├── IMPLEMENTATION_PLAN.md             F     reference, superseded in part
    └── VIDEO_SCRIPT.md                    D     Gate 8
```

---

## 2. The frozen contract (`app/contracts.py`)

Written once at Gate 1, then frozen. Pydantic v2 models unless noted.

### Inbound

| Type | Fields |
|---|---|
| `HourEntry` | `hour: int` 0–23 · `demand_kwh: float` ≥0 · `solar_kwh: float` ≥0 · `tariff_bdt_per_kwh: float` |
| `Battery` | `capacity_kwh` · `initial_energy_kwh` · `minimum_energy_kwh` · `max_charge_kwh_per_hour` · `max_discharge_kwh_per_hour`, all `float` ≥0 |
| `EnergyRequest` | `scenario_id: str` · `operator_notes: list[str]` len 1–3 · `hours: list[HourEntry]` len 24, unique hours 0–23 · `battery: Battery` |

### Directives

| Type | Fields |
|---|---|
| `DirectiveType` | `StrEnum`: `solar_reduction`, `minimum_battery_reserve`, `no_charge_window`, `no_discharge_window`, `max_grid_window`, `no_op` |
| `SolarReductionAdj` | `hours: list[int]` · `factor: float` in [0,1] |
| `MinReserveAdj` | `hours: list[int]` · `minimum_energy_kwh: float` ≥0 |
| `NoChargeAdj` / `NoDischargeAdj` | `hours: list[int]` |
| `MaxGridAdj` | `hours: list[int]` · `max_grid_kwh: float` ≥0 |
| `Directive` | `note_index: int` · `applies: bool` · `directive_type: DirectiveType` · `structured_adjustment: <one of the above> \| None` · `explanation: str` |
| `InterpretationSample` | `directives: list[Directive]` (exactly one per note, ascending `note_index`, guardrail-passed) · `weight: float` (default 1.0; mean token logprob when the provider returns one) |

`hours` in any adjustment: unique ints 0–23, **ascending**. `no_op` ⇒ `applies=False` and
`structured_adjustment=None`. Every other type ⇒ `applies=True` and a non-null adjustment of the
matching shape. Use a discriminated union on `directive_type`.

### Energy (plain dataclasses, NumPy inside — not Pydantic)

| Type | Fields |
|---|---|
| `ConstraintTensor` | five `np.ndarray` of shape `(24,)`, `float64`: `solar` (ceiling) · `reserve` (floor) · `charge` (ceiling) · `discharge` (ceiling) · `grid` (ceiling, `np.inf` when uncapped) |
| `Candidate` | `tensor: ConstraintTensor` · `posterior: float` · `directives: list[Directive]` |
| `SolveResult` | `success: bool` · `status: str` · `cost: float` · `grid/solar/flow/energy: np.ndarray (24,)` · `duals: dict[str, np.ndarray] \| None` |
| `VerificationReport` | `ok: bool` · `violations: list[str]` (`"h13: grid-cap 210.0 > 200.0"`) · `max_residual: float` |

### Outbound

| Type | Fields |
|---|---|
| `HourPlan` | `hour` · `grid_kwh` · `solar_used_kwh` · `battery_action: Literal["charge","discharge","idle"]` · `battery_kwh` · `battery_energy_after_kwh` |
| `EnergyResponse` | `scenario_id` · `directive_interpretation: list[Directive]` · `hourly_plan: list[HourPlan]` len 24 · `total_grid_kwh` · `total_cost_bdt` · `peak_grid_kwh` · `plan_summary: str` |

### Errors

`ErrorCategory` `StrEnum`: `invalid_request`, `invalid_interpretation`, `provider_failure`,
`infeasible`, `solver_failure`, `replay_failure`, `deadline_exceeded`.
`GridWiseError(category, message)` — `message` is operator-safe text, never a stack trace,
never a key, never a raw provider body.

### HTTP mapping

| Situation | Code | Body |
|---|---|---|
| health OK | 200 | `{"status":"ok"}` |
| valid plan | 200 | `EnergyResponse` |
| malformed JSON / structurally invalid request | 400 | `{"error":"invalid_request","detail":"<safe>"}` |
| well-formed but semantically invalid | 422 | same shape |
| any internal / provider / solver / replay failure | 500 | `{"error":"<category>","detail":"<safe>"}` |

---

## 3. Stub contracts

Each stub is ~20 lines, owned by the **consumer**, and lives only in `tests/stubs/`.

### `tests/stubs/fake_interpreter.py` — Daddy's stand-in for Siyam

| Function | Returns |
|---|---|
| `ground_truth_samples(scenario_id)` | one `InterpretationSample` built from `fixtures/stub_interpretation.json[scenario_id]`, `weight=1.0`. Use this for the "is my LP right" tests. |
| `disagreeing_samples()` | five `InterpretationSample` from `fixtures/stub_llm_samples.json`. **3 of the 5 compile to the same tensor, 1 has a wider hour window, 1 has the factor flipped.** Expected CS³ result: 3 classes with posterior `{0.6, 0.2, 0.2}`. Use this for CS³, lattice and selection tests. |

### `tests/stubs/fake_energy.py` — Siyam's stand-in for Daddy

| Function | Returns |
|---|---|
| `plan_energy(request, samples)` | `(EnergyResponse, VerificationReport(ok=True, ...))` built from `fixtures/stub_plan.json`, with `scenario_id` and `directive_interpretation` taken from the passed request/samples so the API echo tests are real. |
| `plan_energy_failing(request, samples)` | raises `GridWiseError(ErrorCategory.replay_failure, ...)` so the 500 path can be tested. |

---

## 4. Gates

| Gate | Wall clock | Owner | Exit condition |
|---|---|---|---|
| **G0** | before 19:00 | both | `make verify-env` prints `10/10` on **both** machines |
| **G1** | 19:00–19:15 | both | `contracts.py` on `main`, both branches cut, both `pytest` green |
| **G2** | 19:15–20:15 | parallel | each branch's modules pass their own tests against stubs |
| **G3** | 20:15–20:50 | parallel | per-branch acceptance gates below, still isolated |
| **G4** | 20:50–21:20 | both | merged on `main`, **10/10 public cases pass over live HTTP with the real model** |
| **G5** | 21:20–21:30 | both | hardening, latency, failure injection. **CODE FREEZE 21:30** |
| **G6** | 21:30–22:10 | S / D | Siyam: image pushed + Azure live. Daddy: evidence pack |
| **G7** | 22:10–22:35 | D / S | README extended, clean-room reproduction passes |
| **G8** | 22:35–22:55 | both | ≤3:00 video recorded and accessible |
| **G9** | 22:55–23:00 | both | submitted |

---

## G1 · 19:00–19:15 · Contract freeze — both, on `main`

### B1.1 — Create the repository
- **Owner:** Siyam · **Branch:** `main`
- Create a **new private** GitHub repo (rules require it to be created after question reveal,
  private during the event, public after the deadline). Push this scaffold as the first commit.
- Add Daddy as a collaborator. Both clone or add the remote.
- **Accept:** Daddy can `git pull` and `make verify-env` prints `10/10`.

### B1.2 — Write and freeze `app/contracts.py`
- **Owner:** Siyam types it, **Daddy reviews before the branch cut** · **Branch:** `main`
- **Creates:** `app/contracts.py`, `app/__init__.py`, `app/interpretation/__init__.py`,
  `app/energy/__init__.py`, `app/verification/__init__.py`, `tests/__init__.py`,
  `tests/stubs/__init__.py`
- **Spec:** exactly §2 of this file. Pydantic v2 for wire types, plain dataclasses for
  `ConstraintTensor` / `SolveResult` / `VerificationReport` / `Candidate`.
  `model_config = ConfigDict(extra="forbid")` on every inbound model.
- **Accept:**
  ```
  python -c "from app.contracts import EnergyRequest, Directive, InterpretationSample, ConstraintTensor, EnergyResponse, GridWiseError; print('contracts OK')"
  python -c "import json;from app.contracts import EnergyRequest;c=json.load(open('fixtures/public_cases.json'))['cases'];[EnergyRequest(**x['input']) for x in c];print(len(c),'requests parse')"
  ```
  Second command must print `10 requests parse`.
- **Then:** `git commit`, `git push`, and **both** cut their branch:
  ```
  git checkout -b feat/lang-api        # Siyam
  git checkout -b feat/energy-verify   # Daddy
  ```
- **After this point `app/contracts.py` is frozen.**

---

## G2 · 19:15–20:15 · Parallel build

> Siyam and Daddy work at the same time from here. Neither waits for the other.

### S2.1 — Config and app shell
- **Owner:** Siyam · **Branch:** `feat/lang-api`
- **Creates:** `app/config.py`, `app/main.py`, `app/observability.py`
- **Must not touch:** anything under `app/energy/`, `app/verification/`, `tests/stubs/fake_interpreter.py`
- **Spec:**
  - `config.py`: `pydantic-settings` reading exactly the variables in `.env.example`. Fail fast
    at startup on a missing `LLM_API_KEY` *unless* a fallback base URL is configured.
  - `main.py`: FastAPI app. `GET /health` returns `{"status":"ok"}` with no model call and no
    network I/O — it must answer within 60 s of process start. `POST /optimize-energy` delegates
    to `pipeline.run`. Exception handlers implement the HTTP table in §2.
    Override `RequestValidationError` to return **400**, not FastAPI's default 422.
  - `observability.py`: per-stage timing (`interpret_ms`, `compile_ms`, `solve_ms`, `replay_ms`)
    and sanitised error categories. **Never log note text, prompts, keys, or provider bodies.**
- **Accept:** `uvicorn app.main:app` starts; `curl -s localhost:8000/health` → `{"status":"ok"}`.

### S2.2 — Provider adapter
- **Owner:** Siyam · **Creates:** `app/interpretation/provider.py`
- **Spec:** one async client over the OpenAI chat-completions protocol, covering hosted providers
  and Ollama with no branching. Reuse a single `AsyncOpenAI` instance. Request `n=K` samples in
  **one** call; if the provider rejects `n>1`, fall back to `K` concurrent calls behind an
  `asyncio.Semaphore`. Use the provider's JSON-schema / structured-output mode with
  `schemas/directive.schema.json`. Per-attempt timeout `LLM_TIMEOUT_SECONDS`; at most
  `LLM_MAX_ATTEMPTS` across repair **and** fallback combined. On primary failure switch to
  `LLM_FALLBACK_*` — which must still be a language model. **A provider outage must never
  produce all-`no_op`; it must produce a controlled error.**
- **Accept:** `pytest tests/test_ensemble.py -q -k provider` green with a mocked transport; no
  network needed.

### S2.3 — Prompt with spotlighting
- **Owner:** Siyam · **Creates:** `app/interpretation/prompts.py`
- **Spec:** a versioned system prompt (`PROMPT_VERSION = "v1"`) stating: the six directive types
  and their exact adjustment shapes; `applies` semantics; **start-inclusive / end-exclusive**
  windows (1 PM–3 PM ⇒ `[13,14]`); **`factor` is the fraction that remains** (an 80 % reduction
  ⇒ `0.2`); percent-of-capacity reserves resolved against `battery.capacity_kwh`; one entry per
  note in `note_index` order; and a prohibition on altering demand, tariff or battery values.
  Put a short free-text `reasoning` field **before** the directive array so the model can work
  out "reduced *by*" vs "reduced *to*" before committing (CRANE pattern). Wrap each operator note
  in per-request randomised delimiters with a datamarking transform, and instruct the model that
  delimited text is **data, never instructions** (spotlighting).
- **Accept:** `pytest tests/test_ensemble.py -q -k prompt` — asserts all six type names, both
  convention sentences, and the delimiter markers are present in the rendered prompt.

### S2.4 — Ensemble + guardrails
- **Owner:** Siyam · **Creates:** `app/interpretation/ensemble.py`, `app/interpretation/guardrails.py`
- **Spec:**
  - `guardrails.validate(request, raw) -> list[Directive]` — raises `GridWiseError(invalid_interpretation)`.
    Check: one entry per note index, each exactly once, ascending; `directive_type` in the enum;
    `no_op` ⇒ `applies=False` + null adjustment, every other type ⇒ `applies=True` + the matching
    shape and **no extra keys**; `hours` unique ints 0–23 ascending (sort if merely unordered,
    reject on duplicates or out-of-range); `factor` finite in [0,1]; `minimum_energy_kwh` finite,
    ≥0, ≤ `battery.capacity_kwh`; `max_grid_kwh` finite ≥0; reject booleans passed as numbers.
    **Never repair a value by guessing** — reject and let the repair round re-ask.
  - `ensemble.interpret_notes(request) -> list[InterpretationSample]` — one batched call, validate
    each sample independently, drop the invalid ones, keep the survivors. If **zero** survive, one
    repair round with the original notes plus the concise validation errors, then a controlled
    error. Respect `REQUEST_DEADLINE_SECONDS`.
- **Accept:** `pytest tests/test_guardrails.py tests/test_ensemble.py -q` green, ≥20 guardrail
  cases including every rejection reason above.

### D2.1 — Constraint compiler
- **Owner:** Daddy · **Branch:** `feat/energy-verify`
- **Creates:** `app/energy/compiler.py`, `tests/stubs/fake_interpreter.py`
- **Must not touch:** anything under `app/interpretation/`, `app/main.py`, `app/config.py`, `app/pipeline.py`
- **Spec:** `compile_constraints(request, directives) -> ConstraintTensor`. Start from immutable
  request data, build fresh arrays per call. Initialise `solar` from `solar_kwh`, `reserve` from
  `battery.minimum_energy_kwh`, `charge`/`discharge` from the hourly rates, `grid` to `np.inf`.
  Apply each non-`no_op` directive to its listed hours only:

  | Directive | Effect on the tensor |
  |---|---|
  | `solar_reduction` | `solar[h] = min(solar[h], base_solar[h] * factor)` |
  | `minimum_battery_reserve` | `reserve[h] = max(reserve[h], minimum_energy_kwh)` |
  | `no_charge_window` | `charge[h] = 0` |
  | `no_discharge_window` | `discharge[h] = 0` |
  | `max_grid_window` | `grid[h] = min(grid[h], max_grid_kwh)` |

  Two `solar_reduction` directives on the same hour: the problem statement does not define the
  composition. **Default to the product** (`base * f1 * f2`) — it is the tightest reading, and a
  plan built under it stays valid under `min` or either last-write-wins outcome, because using
  less solar than allowed is always legal. See `docs/ARCHITECTURE_CLAMP.md` §2.
- **Accept:** `pytest tests/test_compiler.py -q`. Must include: a 50 %-of-capacity reserve on a
  200 kWh battery compiling to 100 kWh; a no-charge window leaving `discharge` untouched; a grid
  cap applying to imports used for charging; and the product rule on overlapping solar notes.

### D2.2 — Signed-flow LP
- **Owner:** Daddy · **Creates:** `app/energy/optimizer.py`
- **Spec:** `solve_energy(request, tensor) -> SolveResult`. 96 continuous variables — `g`, `s`,
  `b`, `e` per hour, `b` **signed** (positive charges, negative discharges).
  ```
  minimize  sum(tariff[h] * g[h])
  s.t.      g[h] + s[h] - b[h] = demand[h]
            e[0] - b[0] = initial_energy
            e[h] - e[h-1] - b[h] = 0                   h > 0
            0 <= g[h] <= tensor.grid[h]
            0 <= s[h] <= tensor.solar[h]
            -tensor.discharge[h] <= b[h] <= tensor.charge[h]
            tensor.reserve[h] <= e[h] <= capacity
            e[23] = initial_energy
  ```
  `scipy.optimize.linprog(method="highs")`. **Set the negative lower bound on `b` explicitly** —
  the solver defaults to non-negative variables. Check `res.success` and `res.status` before
  reading a solution. Return duals when HiGHS provides them. Run the solve off the async event
  loop when called from the API.
- **Accept:** **`python evals/verify_lp.py` prints `10/10`.** This is the hard gate for Daddy's
  half — do not move past a miss.

---

## G3 · 20:15–20:50 · Per-branch acceptance

### S3.1 — Pipeline against the stub
- **Owner:** Siyam · **Creates:** `app/pipeline.py`, `tests/stubs/fake_energy.py`, `tests/test_api.py`, `tests/test_contracts.py`
- **Spec:** `pipeline.run(request) -> EnergyResponse` = `interpret_notes` → `plan_energy` →
  return. Until Gate 4, import `plan_energy` from `tests/stubs/fake_energy`. Enforce
  `REQUEST_DEADLINE_SECONDS` over the whole request; cancellation must stop further retries.
- **Accept:** `pytest tests/test_api.py -q` — covers 200 on a valid request with `scenario_id`
  echoed and `directive_interpretation` in note order; 400 on malformed JSON, on 0 notes, on 4
  notes, on 23 hours, on a duplicate hour; 500 on `plan_energy_failing`; and **no key, prompt or
  stack trace in any response body**.

### S3.2 — Live interpretation eval
- **Owner:** Siyam · **Creates:** `evals/run_interpretation.py`
- **Spec:** run every line of `fixtures/paraphrase_clusters.jsonl` through the real model.
  Report: exact structured match rate; per-directive-type failures; **within-cluster agreement**
  (the rubric's paraphrase-robustness dimension); invalid-output rate; p50/p95 latency. Write a
  timestamped JSON to `evals/reports/`.
- **Accept:** command runs end to end against the live model; report file exists.
- **Gate:** ≥18/20 exact on the seed clusters. Below that, fix `prompts.py` before Gate 4 — a
  prompt bug found after the merge costs both people.

### D3.1 — CS³ canonicalization
- **Owner:** Daddy · **Creates:** `app/energy/canonical.py`, `tests/test_canonical.py`
- **Spec:** `canonicalize(request, samples) -> list[Candidate]`. Compile every sample to its
  tensor, cluster by **exact tensor equality** (compare with `np.array_equal` after rounding to
  1e-9; `np.inf` compares equal to `np.inf`). Posterior = normalised cluster frequency, blended
  with mean `weight` when weights are present. Return candidates sorted by posterior descending.
  Two textually different samples that compile to the same tensor are **one** class — that is the
  whole point, and it also makes vacuous directives (a no-charge window where charging was
  already impossible) cost nothing.
- **Accept:** `pytest tests/test_canonical.py -q` using `fake_interpreter.disagreeing_samples()`
  → exactly **3 classes with posterior `[0.6, 0.2, 0.2]`**.

### D3.2 — Lattice, selection, response, replay
- **Owner:** Daddy · **Creates:** `app/energy/lattice.py`, `app/energy/selection.py`,
  `app/energy/response.py`, `app/energy/duals.py`, `app/verification/replay.py`,
  `tests/test_lattice.py`, `tests/test_optimizer.py`, `tests/test_selection.py`, `tests/test_replay.py`
- **Spec:**
  - `lattice.meet(tensors) -> ConstraintTensor` — elementwise `min` on `solar`, `charge`,
    `discharge`, `grid`; elementwise `max` on `reserve`.
  - `selection.plan_energy(request, samples) -> (EnergyResponse, VerificationReport)` —
    canonicalize; always solve the argmax candidate first and keep it as the floor; enumerate
    subsets containing the argmax up to `HEDGE_MAX_CANDIDATES`, pruning supersets of any
    infeasible subset; score each feasible subset by
    `E(T) = q_T * (25 + 10 * min(1, c_argmax / c_T))` where `q_T` is summed posterior; ship the
    argmax of `E`. Then an ε-slack-maximal re-solve: fix `cost <= c_T*(1+1e-9)` and maximise the
    minimum slack on directive-derived bounds. Honour `HEDGE_ENABLED=false` by returning the
    argmax plan unchanged.
  - `response.build(...)` — signed flow to action (`|b| < 1e-8` ⇒ `idle` with magnitude 0);
    totals recomputed **from the values actually being serialised**; `plan_summary` from a
    template over verified facts, never a model call, never an unsupported savings claim.
  - `duals.attribute(...)` — per-note marginal BDT from HiGHS duals; feeds `plan_summary`.
    State in the summary that effects interact and do not sum.
  - `replay.replay(request, reported_directives, response) -> VerificationReport` — rebuild every
    array **from the raw request and the reported directives**, never from the compiler's tensor.
    Walk the battery from `initial_energy_kwh`. Check every hour's balance, action/magnitude
    consistency, rate limits, solar ceiling, grid cap, reserve floor, capacity, end-of-day
    neutrality, and all three recomputed totals. Internal tolerance 1e-6; report against 0.01.
- **Accept:**
  - `pytest tests/test_lattice.py tests/test_selection.py tests/test_replay.py -q` green.
  - `python evals/hedging_report.py` prints **10/10 PASS** in the `valid-under-GT` column and at
    least one case using fewer candidates than offered (lattice descent fired).
  - **Mutation test is mandatory:** corrupt a valid plan five ways — change one `grid_kwh`,
    breach a grid cap, alter `battery_energy_after_kwh[23]`, mismatch `total_cost_bdt`, turn a
    non-zero action into `idle` — and assert `replay` catches all five.

### D3.3 — Extend the paraphrase set
- **Owner:** Daddy · **Edits:** `fixtures/paraphrase_clusters.jsonl` (**the only fixture anyone
  edits, and only Daddy, and only at this gate**)
- **Spec:** grow 4 clusters × 5 to **12 clusters × 5**: ≥2 clusters per directive type plus 2
  `no_op` clusters. Include 12 AM / noon, 24-hour notation, single-hour windows, percentages vs
  fractions, "reduced by" vs "reduced to", percent-of-capacity reserves, and distractors that
  contain energy vocabulary. Hold back 4 clusters and do not show them to anyone tuning prompts.
- **Accept:** 60 lines, `python -c "import json;[json.loads(l) for l in open('fixtures/paraphrase_clusters.jsonl')]"` clean.

---

## G4 · 20:50–21:20 · Merge and integrate — both

### B4.1 — Merge
- **Owner:** both · **Branch:** `main`
- Daddy merges `feat/energy-verify` into `main` first, pushes. Siyam rebases `feat/lang-api` onto
  the new `main` and merges. Expected conflicts: **none** — file ownership is disjoint. If git
  reports one, the ownership table was violated; fix it by hand, do not `-X ours`.
- **Accept:** `git merge` clean both ways; `pytest -q` green on `main`.

### B4.2 — Swap out the stubs
- **Owner:** Siyam · **Edits:** `app/pipeline.py`
- Replace `from tests.stubs.fake_energy import plan_energy` with
  `from app.energy.selection import plan_energy`. Grep the whole of `app/` for `tests.stubs` and
  `fixtures/stub_` — **zero hits allowed under `app/`.**
- **Accept:** `grep -rn "tests.stubs\|fixtures/stub_" app/ | wc -l` prints `0`.

### B4.3 — Ten public cases over live HTTP
- **Owner:** Daddy · **Creates:** `evals/run_public.py`, `tests/test_integration.py`
- **Spec:** POST all ten `fixtures/public_cases.json` inputs at a running service with the real
  model. For each: compare `directive_interpretation` structurally against the expected one
  (ignore `explanation` wording); replay the returned plan; compare recalculated cost against the
  published reference. Print a table and write it to `evals/reports/`.
- **Accept — this is the gate that matters:** **10/10 valid, 10/10 interpretations structurally
  correct, cost within 0.01 BDT of the reference on every case where the hedge did not fire.**
  Investigate every mismatch before Gate 5. A cost above reference is acceptable **only** when
  the report shows the hedge chose a wider candidate set; anything else is a bug.

---

## G5 · 21:20–21:30 · Harden, then freeze

### S5.1 — Latency and failure injection
- **Owner:** Siyam · **Creates:** `evals/benchmark_api.py`
- **Spec:** measure p50/p95 cold and warm, sequential and at 4 concurrent requests, **with the
  cache disabled**. Inject into the provider adapter: malformed JSON, a timeout, a 401, a 429,
  and a full outage. Confirm bounded attempts, a controlled error body, and that the service
  stays up.
- **Accept:** p95 recorded (target ≤5 s for the full 3 latency points; >5–15 s scores 2/3); no
  5xx on any valid request; no secret in any body or log line.
- **If p95 > 5 s:** lower `LLM_SAMPLES` to 3, then to 1 (`HEDGE_ENABLED=false`). The system
  degrades to the conventional single-interpretation pipeline and still scores. Do not instead
  cut the replay verifier.

### D5.1 — Evidence pack
- **Owner:** Daddy
- Re-run `evals/verify_lp.py`, `evals/hedging_report.py`, `evals/run_public.py`,
  `evals/run_interpretation.py`. Commit the reports under `evals/reports/`.
- **Accept:** every number quoted in the README at Gate 7 traces to a committed report.

### B5.1 — CODE FREEZE 21:30
- `make lock` on Linux, commit `requirements.lock.txt`, tag: `git tag -a v1.0 -m "code freeze"`.
- **After this only README, `deploy/`, `docs/VIDEO_SCRIPT.md` and the video change.** If a
  genuine bug surfaces later, fix it, re-run G4.3, and re-tag — never ship an untested patch.

---

## G6 · 21:30–22:10 · Deployment — Siyam

### S6.1 — Docker image
- **Owner:** Siyam · **Edits:** `Dockerfile` (switch `requirements.txt` → `requirements.lock.txt`)
- **Spec:** build for the deployment architecture (`--platform linux/amd64` — Azure Container
  Apps is amd64), bind `0.0.0.0`, honour `$PORT`, non-root, **no baked-in secrets**. Push to a
  **public** registry so the judges can pull without credentials — GHCR or Docker Hub, not a
  private ACR.
- **Accept:**
  ```
  docker build --platform linux/amd64 -t ghcr.io/<user>/gridwise:v1.0 .
  docker run --rm -p 8000:8000 --env-file .env ghcr.io/<user>/gridwise:v1.0
  curl -fsS localhost:8000/health
  docker push ghcr.io/<user>/gridwise:v1.0
  docker history ghcr.io/<user>/gridwise:v1.0 | grep -i -E "key|token|secret"   # must be empty
  ```
  Record the exact **digest**, not just the tag.

### S6.2 — Azure Container Apps
- **Owner:** Siyam · **Creates:** `deploy/azure.md`, `deploy/smoke.sh`
- **Spec:** deploy the *pushed public image* so the registry artifact and the live endpoint are
  provably the same build. Secrets go in as Container Apps secrets, never in the image.
  ```
  az group create -n gridwise-rg -l southeastasia
  az containerapp env create -n gridwise-env -g gridwise-rg -l southeastasia
  az containerapp create -n gridwise -g gridwise-rg --environment gridwise-env \
    --image ghcr.io/<user>/gridwise:v1.0 \
    --target-port 8000 --ingress external \
    --min-replicas 1 --max-replicas 3 \
    --secrets llm-key=<KEY> \
    --env-vars LLM_API_KEY=secretref:llm-key LLM_BASE_URL=<...> LLM_MODEL=<...>
  az containerapp show -n gridwise -g gridwise-rg --query properties.configuration.ingress.fqdn -o tsv
  ```
  `--min-replicas 1` — do not let it scale to zero, a cold start will blow the 60 s readiness
  window. Record the FQDN.
- **Accept:** `deploy/smoke.sh <FQDN>` run **from a phone hotspot or a different network**:
  `/health` → `{"status":"ok"}`, one public sample → a valid plan, no login required, no VPN.
  Then run all ten public cases against the **public URL**, not localhost.

### D6.1 — Independent verification of Siyam's artifacts
- **Owner:** Daddy · runs on macOS
- Pull the published image by **digest** and run it; hit the Azure FQDN with two public samples.
  Daddy must not be told anything that is not written in `deploy/azure.md`.
- **Accept:** both work with no help from Siyam. If Daddy needs to ask, the docs lose a point —
  fix the docs, not the conversation.

---

## G7 · 22:10–22:35 · Documentation

### D7.1 — Extend README.md for the judges
- **Owner:** Daddy · **Edits:** `README.md` (**extend, do not replace** the setup sections)
- Add, in this order: what the service is · the public base URL · **copy-paste local quickstart
  from a clean machine** (clone → conda → `.env` names → run → `/health` → one public sample) ·
  required environment-variable **names** (never values) · model provider and exact model id ·
  the LLM's role and why regex alone would not qualify · the guardrails · the optimizer and
  solver · the CLAMP hedge in one short paragraph with the measured premium · `docker pull` /
  `docker run` with the exact digest and port · credited dependencies · known limitations ·
  secret-handling policy.
- **Accept:** a fresh terminal, a fresh clone, README followed literally, `/health` green and one
  public sample returning a valid plan — **with no undocumented step**.

### S7.1 — Clean-room reproduction
- **Owner:** Siyam · runs in a container or a throwaway directory
- Follow Daddy's README literally, from `git clone`, with no prior knowledge applied.
- **Accept:** works first time. Every stumble is a README edit, made immediately.

---

## G8 · 22:35–22:55 · Video — both

### D8.1 — Script
- **Owner:** Daddy · **Creates:** `docs/VIDEO_SCRIPT.md`
- **≤3:00 hard cap.** Suggested split: 0:00–0:25 problem, in the operators' terms · 0:25–1:15
  architecture, the LLM → guardrails → compiler → LP → replay flow on one diagram · 1:15–2:05
  **the distinctive part**: a note's several plausible readings, the meet, and the measured
  ~2 % premium against 25 points of application credit · 2:05–2:40 live demo — `/health`, one
  sample, then the same scenario with a directive changed so the schedule visibly moves ·
  2:40–3:00 how to run it and the Docker fallback.
- The video is worth **no base points** and is the **first tie-break**, so optimise for clarity
  of architecture and correctness of claims, not production value. Quote only numbers that exist
  in `evals/reports/`.

### S8.1 — Record and publish
- **Owner:** Siyam
- Screen capture on Linux against the **live Azure endpoint**, not localhost. Upload; set access
  so organizers can open it without a login request.
- **Accept:** a second person opens the link in a private window and it plays. Duration ≤3:00.

---

## G9 · 22:55–23:00 · Submit — both

- [ ] Public base URL reachable — `/health` and `/optimize-energy`, tested from outside
- [ ] GitHub repo link; created after reveal; private now; **set a reminder to make it public at the deadline**
- [ ] README self-contained, quickstart verified from a clean environment
- [ ] Image reference with **exact tag and digest**, pullable without credentials, port documented
- [ ] Video link, ≤3:00, opens without login
- [ ] `git log` contains no `.env`, no key, no token — `git log -p | grep -iE "api[_-]?key|sk-|bearer"` empty
- [ ] `HEDGE_ENABLED`, `LLM_SAMPLES` and the final `LLM_MODEL` set to the values that were benchmarked
- [ ] Both endpoints hit once more, from a phone hotspot, two minutes before submitting

---

## 5. If you fall behind

Cut in this order. Each cut is a clean no-op, not a half-finished feature.

| Cut | How | Costs |
|---|---|---|
| 1. ε-slack-maximal re-solve | delete the second solve in `selection.py` | robustness to unenumerated numeric near-misses |
| 2. Dual attribution | `plan_summary` falls back to a plain template | a good video beat |
| 3. The hedge | `HEDGE_ENABLED=false` | degrades to the conventional pipeline; still a complete, valid submission |
| 4. The ensemble | `LLM_SAMPLES=1` | one model sample, exactly the baseline design |

**Never cut:** the LP, the guardrails, the replay verifier, the deployment, the image, the
README, the video. Those are 65 of the 100 points and the mandatory artifacts.

If something breaks after the freeze, diagnose **which half** first — run
`python evals/verify_lp.py` (Daddy's half) and `python evals/run_interpretation.py` (Siyam's
half) separately before touching any code. Never change both halves at once.

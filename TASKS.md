**GridWise implementation checklist**

Detailed design and rationale: [implementation plan](docs/IMPLEMENTATION_PLAN.md). A = language/API/deployment owner; B = optimization/verification owner. Both = shared agreement or cross-review. Check an item only when its stated evidence exists. This checklist tracks planned work; no service has been implemented yet.

**Planning completed**

- [x] Read the problem statement, evaluation guide, and all ten public case definitions.
- [x] Record required endpoints, directives, objective, scoring, latency limits, and deliverables.
- [x] Replay all ten supplied reference schedules for arithmetic, energy constraints, directives, neutrality, and totals. All passed; independent optimality certification remains implementation work.
- [x] Design module boundaries, exact signed-flow LP, two-person ownership, and four-hour schedule.
- [x] Record unresolved specification details and separate optional extensions from core work.

**Gate 1 — shared contracts and working dependencies, target 15 minutes**

- [ ] Both: agree ownership and freeze request, directive, constraint, solver-result, and response types.
- [ ] Both: confirm exact six directive variants and end-of-hour reserve semantics.
- [ ] Both: confirm runtime model credentials, quota, provider, and selected host are available.
- [ ] Both: resolve organizer questions where possible, especially overlapping solar reductions; record remaining assumptions.
- [ ] A: scaffold FastAPI, configuration, exception handlers, dependency pins, and `.env.example`.
- [ ] A: add request validation, including 24 unique hours and 1–3 nonempty notes.
- [ ] B: build a loader for the supplied sample pack without modifying it.
- [ ] Both: agree the signed battery convention, function signatures, and error categories.

**Gate 2 — independently working modules, target 50 minutes**

- [ ] A: implement one batched generative-model interpretation call for all notes.
- [ ] A: implement exact directive variants, note mapping, `applies`, ranges, and adjustment shapes.
- [ ] A: cover fraction remaining, percent reserve, AM/PM/noon, and half-open intervals.
- [ ] A: enforce at most two model attempts across repair and fallback; no regex-only production path.
- [ ] A: start a deployment skeleton early enough to expose hosting problems.
- [ ] B: compile per-hour solar, reserves, charge/discharge limits, and grid caps with provenance.
- [ ] B: implement the 96-variable continuous LP and explicit negative battery-flow bounds.
- [ ] B: enforce energy balance, battery transitions, solar bounds, all directives, and final neutrality.
- [ ] B: check solver status and handle infeasibility without relaxing directives.
- [ ] B: convert signed flows into public actions and calculate totals from returned values.
- [ ] B: implement replay that checks original directives independently of compiler arrays.
- [ ] B: verify all ten optimizer-only cases against trusted reference directives and published costs.

**Gate 3 — complete real-model pipeline, target 75 minutes**

- [ ] A: `GET /health` returns the documented readiness JSON.
- [ ] Both: `POST /optimize-energy` uses live interpretation → guardrails → compiler → optimizer → replay.
- [ ] Both: remove test doubles from the submission execution path.
- [ ] A: preserve scenario ID and exact note indexes/order in successful responses.
- [ ] B: produce 24 valid hourly entries and a fact-based summary.
- [ ] B: verify the serialized JSON round trip and recalculate all totals.
- [ ] Both: complete all ten public HTTP requests and investigate every interpretation, validity, or cost mismatch.

**Gate 4 — correctness beyond public wording, target 120 minutes**

- [ ] A: create 60 independently checked language cases, with at least ten per type and a held-out portion.
- [ ] A: test new percentages, fractions, time expressions, relevance traps, and mixed notes.
- [ ] A: verify ordinary numbers work and booleans, non-finite values, invalid mappings, and unsupported types fail safely.
- [ ] B: test solar curtailment, zero rates, flat/zero tariffs, fractional values, tight caps, and final-hour restrictions.
- [ ] B: mutate valid schedules and confirm replay detects balance, cap, action, neutrality, and totals errors.
- [ ] Both: test note permutation, irrelevant-note insertion, scaling, and constraint-tightening relationships.
- [ ] A: inject malformed model output, provider timeouts, throttling, and authentication failures.
- [ ] A: enforce structural-input HTTP 400, optional semantic 422, and controlled internal/provider errors.
- [ ] Both: confirm no invalid model output silently becomes `no_op` or invented constraints.
- [ ] Both: save evaluation results with model/prompt versions and clearly distinguish local validation from organizer ground truth.

**Gate 5 — reachable service and Docker fallback, target 160 minutes**

- [ ] A: implement request deadline, bounded concurrency, stage timing, and cancellation-aware retries.
- [ ] A: verify solver work does not block the async event loop during concurrent requests.
- [ ] A: build a pinned-dependency image for the deployment architecture and bind to `0.0.0.0`.
- [ ] A: keep credentials out of source, image layers, logs, and response errors.
- [ ] A: deploy both exact endpoints at one externally reachable base URL without judge login.
- [ ] A: publish a pullable image with exact tag/digest and runtime environment instructions.
- [ ] B: test `/health` readiness within 60 seconds from clean startup.
- [ ] B: test both endpoints from outside the development environment.
- [ ] B: benchmark uncached valid requests and realistic concurrency; record p50/p95 and failures.
- [ ] Both: verify requests finish below 30 seconds, aim for p95 ≤5 seconds, and document actual results.
- [ ] Both: verify runtime model quota and endpoint/image availability for the judging window.

**Gate 6 — reproducibility, target 190 minutes**

- [ ] A: document clean setup, dependency installation, environment-variable names, provider/model, and exact start command.
- [ ] A: document curl checks for both endpoints and a command that runs public samples.
- [ ] A: explain interpretation, guardrails, compiler, optimizer, replay, limitations, and credited dependencies.
- [ ] A: document exact Docker pull/run commands, port, and runtime secret configuration.
- [ ] B: reproduce the README from a fresh environment without undocumented intervention.
- [ ] B: pull and run the submitted image, reach health, and execute a real-model public sample.
- [ ] Both: confirm the documented expected costs and tolerances match measured results.

**Gate 7 — video and submission, target 240 minutes**

- [ ] Both: record a video ≤3 minutes explaining the problem, architecture, LLM → guardrail → solver flow, and run/test procedure.
- [ ] Both: include measured evidence, such as a passing sample run and the effect of an operator directive.
- [ ] Both: verify the video is accessible to organizers.
- [ ] Both: confirm repository creation timing and private-during-event/public-after-deadline rules.
- [ ] A: assemble public base URL, repository link, image tag/digest, configuration instructions, and video link.
- [ ] B: rerun the external health/API smoke tests and inspect the final evaluation report.
- [ ] Both: check required links remain accessible and no secret values are submitted.
- [ ] Both: freeze optional features and submit before the deadline.

**Optional improvements — start only after core gates pass**

- [ ] A: add internal source-span evidence and deterministic normalization of extracted quantity types.
- [ ] A: evaluate selective semantic review; enable only with demonstrated quality gain and acceptable latency.
- [ ] Both: add note-to-constraint-to-replay traces for debugging and the video.
- [ ] B: add counterfactual solves for restriction costs, with clear interaction caveats.
- [ ] A: evaluate a validated interpretation cache only after resolving model-use expectations; key by content/context/version.
- [ ] Both: expand independent adversarial tests based on observed failure categories.

**Evidence to attach before marking the implementation complete**

| Evidence | Location/value to fill during implementation |
|---|---|
| Source revision and dependency lock | Pending |
| Model/provider and prompt version | Pending |
| Public cases: interpretation + validity + cost | Pending; target 10/10 |
| Held-out language evaluation | Pending |
| Numerical and replay-mutation tests | Pending |
| External latency/failure report | Pending |
| Public API base URL | Pending |
| Pullable image tag/digest | Pending |
| Fresh-environment reproduction result | Pending |
| Repository timing/visibility check | Pending |
| Accessible ≤3-minute video | Pending |

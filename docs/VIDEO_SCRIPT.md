# GridWise — video script

**Hard cap: 3:00.** No base points ride on this video — it is the first tie-break — so the goal is
clarity of architecture and correctness of every claim, not production value. Every number below
is quoted from a committed file under `evals/reports/`; do not state a number that isn't there.

Record on Linux (Siyam), screen-captured against the **live Azure endpoint**, not localhost.

---

## 0:00–0:25 — The problem, in the operators' terms

**Say:**
> "A campus energy operator has a 24-hour demand, solar, and tariff forecast, a battery, and one
> to three plain-English notes — 'cut solar during panel cleaning,' 'no charging during the outage
> window.' GridWise turns those notes into the cheapest schedule that still obeys every one of
> them — and proves, independently, that it does."

**Show:** the problem statement's sample notes, or just say it over a blank terminal. No demo yet.

## 0:25–1:15 — Architecture

**Show:** `docs/architecture_flow.png` — a single-row flowchart of the actual shipped pipeline
(rendered from `docs/architecture_flow.mmd`; re-render with `npx @mermaid-js/mermaid-cli` if it
ever needs updating). It's wider than 16:9, so letterbox it (black bars top/bottom) rather than
stretching it. Do **not** use the more detailed flowchart in `docs/ARCHITECTURE_CLAMP.md` §3.8 —
that one shows a calibrated plausible-set step (`S_alpha` / `HEDGE_ALPHA`) that was never actually
wired into `app/energy/selection.py`; see `README.md`'s *Known limitations* section.

**Say:**
> "A language model is mandatory here, not optional — 'reduced by 80%' and 'reduced to 80%' share
> every keyword but mean opposite things, and no regex layer can be measured for paraphrase
> robustness, which the rubric scores directly. The model emits one structured directive per note,
> in one of six types. Deterministic guardrails validate that output — wrong shape, wrong range, a
> boolean where a number belongs, all rejected, never silently repaired. Accepted directives
> compile into five 24-hour bound arrays, a 96-variable linear program finds the cheapest schedule
> with SciPy's HiGHS solver, and an independent replay verifier — written separately from the
> compiler, so one bug can't fool both — rebuilds every number from the raw request before the
> response ever leaves the API."

**Cite:** `evals/reports/verify_lp_20260918_155109.txt` — LP optimum matches all ten published
reference costs to **0.0000 BDT**, and all ten reference schedules replay clean.

## 1:15–2:05 — The distinctive part: hedging across plausible readings

**Say:**
> "Here's the part that isn't in the standard pipeline. The interpretation you *report* and the
> schedule you *ship* are scored separately — the schedule gets replayed against the judge's
> hidden ground truth, which you never see. So instead of betting everything on one reading,
> GridWise samples several interpretations in one batched call, clusters them by whether they
> compile to the *same* constraint tensor — not by comparing text — and reports the majority
> reading. But it *schedules* against the elementwise meet of every reading still worth defending.
> A schedule feasible under that meet satisfies every one of those readings at once, because every
> constraint here is a one-sided bound — a ceiling or a floor — so tightening never conflicts."

**Cite:** `evals/reports/hedging_report_20260918_155109.txt` — measured on all ten public cases
under worst-case synthetic disagreement: mean premium **2.07%**, max **5.67%** — roughly 0.2 of
the 10 optimization points, spent to protect the 25-point interpretation category and the 25-point
constraint-correctness category from ever shipping a plan built on a single wrong reading. One
case (SAMPLE-05) hit an infeasible full meet; the system automatically fell back to 3 of 4
candidates rather than failing outright. When the ensemble agrees — the common case — this costs
nothing.

## 2:05–2:40 — Live demo

Against the **live deployed endpoint** (fill in the FQDN before recording):

```bash
curl -fsS https://<FQDN>/health
# {"status":"ok"}

curl -s -X POST https://<FQDN>/optimize-energy \
  -H "Content-Type: application/json" \
  -d "$(jq '.cases[5].input' fixtures/public_cases.json)" | jq '{total_cost_bdt, hourly_plan: .hourly_plan[10:12]}'
```

**Say while it returns:** "SAMPLE-06 — cloud cover cuts solar to half of forecast from 10 AM to
noon. Hour 10: 75 kWh of solar used, 85 kWh from the grid, total cost 34,090 BDT."

Now change one phrase in the note — "about half" becomes "only about 10 percent" — and re-run:

```bash
jq '.cases[5].input | .operator_notes[0] =
  "Cloud cover during panel inspection will leave only about 10 percent of forecast solar output from 10 AM until noon."' \
  fixtures/public_cases.json > /tmp/demo_changed.json

curl -s -X POST https://<FQDN>/optimize-energy \
  -H "Content-Type: application/json" \
  -d @/tmp/demo_changed.json | jq '{total_cost_bdt, hourly_plan: .hourly_plan[10:12]}'
```

**Say:** "Same hours, a harsher reading of the same note: solar use at hour 10 drops from 75 to 15
kWh, grid import rises to 120, and total cost moves from 34,090 to 36,206 BDT. The schedule
visibly tracks the language — because the compiler and the LP are exact, not approximate."

*(Verified locally before recording: factor 0.5→0.1 on SAMPLE-06 moves hour-10 solar 75→15 kWh,
grid 85→120 kWh, total cost 34,090.00→36,206.00 BDT. Confirm the same shift against the live
endpoint during rehearsal before the real take.)*

## 2:40–3:00 — Running it, and the Docker fallback

**Say:**
> "Everything here is reproducible from a clean clone — conda environment, one `.env` file, one
> uvicorn command. If Azure is unreachable, the exact same image judges can pull runs identically
> locally."

```bash
docker pull ghcr.io/<org>/gridwise@sha256:<digest>
docker run --rm -p 8000:8000 --env-file .env ghcr.io/<org>/gridwise@sha256:<digest>
```

**Close:** "Full setup and every number quoted here are in the README and `evals/reports/`."

---

## Recording checklist

- [ ] FQDN and Docker digest filled in above before the take (see `README.md`'s placeholders)
- [ ] Demo re-verified against the **live** endpoint during rehearsal, not just localhost
- [ ] Total runtime ≤ 3:00
- [ ] Every number spoken matches a file under `evals/reports/` — no number invented for the video
- [ ] No secret visible on screen (terminal history, `.env` contents, API keys)
- [ ] Upload with access set so organizers can open it without a login request

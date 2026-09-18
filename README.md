# GridWise — LLM-assisted campus energy optimization

BUP CSE Fest 2026 · Online Preliminary · `POST /optimize-energy`

## What this is

GridWise is a small FastAPI service for the BUP CSE Fest 2026 GridWise-LLM preliminary. It takes
a 24-hour demand/solar/tariff forecast, a battery spec, and 1–3 free-text operator notes, and
returns the cheapest valid 24-hour grid/solar/battery schedule that honours every note. A language
model interprets the notes into one of six structured directive types; everything downstream —
validation, constraint compilation, optimization, and verification — is deterministic.

## Public base URL

**`https://gridwise.mangowater-ca3ac31c.southeastasia.azurecontainerapps.io`**

- `GET /health` → `{"status":"ok"}`
- `POST /optimize-energy` → interpretation + 24-hour plan

No login, VPN, or allowlisting required. Note there is deliberately no route at `/` — the
specification defines only the two endpoints above, so a browser hitting the bare base URL
correctly gets a `404`; use `/health` to check liveness.

Quick check:

```bash
curl -fsS https://gridwise.mangowater-ca3ac31c.southeastasia.azurecontainerapps.io/health
```

Verified against all ten public cases on this live URL: 10/10 valid, 10/10 interpretation
correct, 10/10 replay clean — see `evals/reports/public_cases_20260918_221601.json`.

## Local quickstart (judges: run this on a clean machine)

```bash
git clone https://github.com/Morningstaaar36/gridwise-llm-energy-optimizer.git
cd gridwise-llm-energy-optimizer

conda env create -f environment.yml
conda activate gridwise

cp .env.example .env
# edit .env: set LLM_BASE_URL, LLM_API_KEY, LLM_MODEL (see the table below for names)

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

In a second terminal — `cd` into the repo first, and activate the environment, since the
commands below read `fixtures/` and use the environment's Python:

```bash
cd gridwise-llm-energy-optimizer
conda activate gridwise

curl -fsS http://localhost:8000/health
# {"status":"ok"}

curl -s -X POST http://localhost:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d "$(python -c "import json;print(json.dumps(json.load(open('fixtures/public_cases.json'))['cases'][0]['input']))")" \
  | python -m json.tool
# a full EnergyResponse: scenario_id, directive_interpretation, hourly_plan, totals, plan_summary
```

Needs nothing beyond the conda environment above — no `jq`, no extra tooling.

### Run all ten public sample cases

With the service running, from the repo root:

```bash
python evals/run_public.py --base-url http://localhost:8000
```

Expected output — a per-case table followed by:

```
=== 10/10 valid | 10/10 interpretation correct | 10/10 replay clean ===
```

For each case it compares `directive_interpretation` structurally against the published
expectation (ignoring free-text wording, per the spec), independently replays the returned
`hourly_plan` against the raw request, and checks the recalculated cost against the published
reference. It also writes a timestamped JSON report under `evals/reports/`.

To point the same check at the deployed service instead:

```bash
python evals/run_public.py --base-url https://gridwise.mangowater-ca3ac31c.southeastasia.azurecontainerapps.io
```

## Required environment variables

Names only — real values go in your own `.env`, never here or in any commit.

| Variable | Purpose |
|---|---|
| `LLM_BASE_URL` | Primary model's OpenAI-compatible base URL |
| `LLM_API_KEY` | Primary model's API key |
| `LLM_MODEL` | Primary model id |
| `LLM_FALLBACK_BASE_URL` | Fallback model's base URL (must still be a language model — never blank in production) |
| `LLM_FALLBACK_API_KEY` | Fallback model's API key |
| `LLM_FALLBACK_MODEL` | Fallback model id |
| `LLM_SAMPLES` | K samples requested per interpretation call (K=1 disables the ensemble hedge) |
| `LLM_TEMPERATURE` | Sampling temperature (ensemble diversity only) |
| `LLM_TIMEOUT_SECONDS` | Per-attempt provider timeout |
| `LLM_MAX_ATTEMPTS` | Batched call + repair rounds, combined |
| `LLM_MAX_COMPLETION_TOKENS` | Cap on the structured-output response |
| `REQUEST_DEADLINE_SECONDS` | Hard ceiling for the whole request (judge times out at 30s) |
| `HEDGE_ENABLED` | `false` degrades to the single-interpretation pipeline |
| `HEDGE_MAX_CANDIDATES` | Cap on the meet-semilattice subset scan |
| `HEDGE_ALPHA` | Reserved for a calibrated plausible-set cutoff — see *Known limitations* |
| `PORT` | Service port |
| `LOG_LEVEL` | Log verbosity |

## Model provider and id

Benchmarked and deployed with:

- **Primary**: `gemini-flash-lite-latest` via Google's OpenAI-compatible endpoint
  (`https://generativelanguage.googleapis.com/v1beta/openai`)
- **Fallback**: `openai/gpt-oss-120b` via Groq (`https://api.groq.com/openai/v1`)

One adapter (`app/interpretation/provider.py`) speaks the OpenAI chat-completions protocol to
both, plus Ollama for offline development — no provider-specific code anywhere.

## The LLM's role, and why regex alone would not qualify

The model reads 1–3 operator notes and emits one structured directive per note (or `no_op`).
This is a semantic task, not a pattern-matching one: "reduced *by* 80%" and "reduced *to* 80%"
share every keyword but mean opposite things (`factor` 0.2 vs 0.8); "keep 50% in reserve" needs
the battery's capacity to resolve to an absolute kWh; a note can use energy vocabulary while being
completely irrelevant to today's schedule. A regex/keyword layer cannot represent the ambiguity a
paraphrase introduces, has no notion of *confidence*, and cannot be measured for paraphrase
robustness — which the rubric scores directly. GridWise instead samples `LLM_SAMPLES` structured
interpretations in one batched call, clusters them by **exact compiled-tensor equality** (CS³,
`app/energy/canonical.py`), and reports the majority reading while scheduling against the meet of
every reading worth defending (`app/energy/selection.py`) — see *The CLAMP hedge* below.

## The guardrails

`app/interpretation/guardrails.py` treats every model output as untrusted until it passes
deterministic checks: one directive per note, in order, each exactly once; `directive_type` in the
supported six; `no_op` ⇒ `applies=false` and a null adjustment, every other type ⇒ `applies=true`
and the matching shape with no extra fields; hours unique integers 0–23 (sorted if merely
unordered, rejected if duplicated or out of range); numeric fields finite and in range; booleans
never accepted where a number is expected. **A rejected value is never repaired by guessing** — it
triggers one bounded repair round with the original notes and the validation errors, then a
controlled `invalid_interpretation` error. Violation messages name note indexes only; note text
never reaches a log line or an error body.

## The optimizer and solver

`app/energy/compiler.py` turns accepted directives into five 24-hour bound arrays (solar ceiling,
reserve floor, charge/discharge ceilings, grid ceiling). `app/energy/optimizer.py` solves a
96-variable signed-flow linear program — `g`, `s`, `b` (signed: + charges, − discharges), `e` per
hour — with `scipy.optimize.linprog(method="highs")`. This formulation is an exact fit for a
lossless battery: every allowed action maps to one signed number, so simultaneous charge/discharge
is structurally impossible and no integer variables are needed.

**Verified exact**: `evals/reports/verify_lp_20260918_155109.txt` — the LP optimum matches all ten
published reference costs to **0.0000 BDT**, and every published reference schedule replays clean
under independent arithmetic.

## The CLAMP hedge

Two things are scored separately: the interpretation you *report*, and the schedule you *ship*
(replayed against the judge's hidden ground truth). GridWise reports the ensemble's majority
reading but schedules against the elementwise **meet** of every reading whose posterior is worth
defending — a schedule feasible under the meet satisfies every one of those readings at once
(the meet is the elementwise tightest bound, so feasibility under it implies feasibility under
each reading individually). This costs a small premium only when the
ensemble actually disagrees; when it agrees, the premium is exactly zero.

**Measured** (`evals/reports/hedging_report_20260918_155109.txt`, worst-case synthetic
disagreement on all ten public cases): mean premium **2.07%**, max **5.67%** — about 0.2 of the
10 optimization points, spent to protect the 25-point interpretation category and the 25-point
constraint-correctness category from a single wrong reading. One case (SAMPLE-05) hit an
infeasible full meet; monotone-infeasibility pruning dropped it to 3 of 4 candidates rather than
failing outright.

## Docker (fallback execution path)

Public image, pullable with no credentials:

```
ghcr.io/morningstaaar36/gridwise:v1.0
digest: sha256:71da3c80494b4b5567e3a6f007c1b4238688d489ea0208e7391cb75c9412c90a
port:   8000  (honours $PORT; binds 0.0.0.0; runs as non-root uid 10001)
```

```bash
# by digest (exact, immutable)
docker pull ghcr.io/morningstaaar36/gridwise@sha256:71da3c80494b4b5567e3a6f007c1b4238688d489ea0208e7391cb75c9412c90a
docker run --rm -p 8000:8000 --env-file .env \
  ghcr.io/morningstaaar36/gridwise@sha256:71da3c80494b4b5567e3a6f007c1b4238688d489ea0208e7391cb75c9412c90a
curl -fsS http://localhost:8000/health
```

The image contains **no credentials** — every layer was scanned for both configured provider
keys before publishing. Supply them at runtime via `--env-file .env` (names in `.env.example`).

> **`--env-file` gotcha, already handled in `.env.example`:** Docker's `--env-file` and Azure
> Container Apps both set these as literal OS environment variables and, unlike
> pydantic-settings' own dotenv reader, do **not** strip a trailing `# comment`. A value written
> `LLM_SAMPLES=5   # note` would reach `int()` with the comment attached and crash startup. Every
> value in `.env.example` therefore keeps its comment on its own line — preserve that if you edit it.

## Credited dependencies

FastAPI + Uvicorn (service), Pydantic v2 / pydantic-settings (strict request/response validation
and config), SciPy (HiGHS solver, via `scipy.optimize.linprog`), NumPy, the `openai` Python SDK
(protocol client — works against OpenAI, Groq, Gemini's OpenAI-compatible endpoint, and Ollama
with zero provider-specific code), httpx, tenacity, pytest / pytest-asyncio, ruff. Development
model access: Google Gemini, Groq, and locally-served Ollama (`qwen3:8b`) as an offline fallback.

## Known limitations

- **Overlapping `solar_reduction` composition is an interim assumption.** The problem statement
  doesn't define how two solar-reduction directives on the same hour combine; GridWise defaults to
  the *product* of their factors — the tightest reading, and provably safe under any looser
  reading since unused solar may always be curtailed for free.
- **`HEDGE_ALPHA` is reserved, not wired up.** The design notes describe a split-conformal
  plausible-set cutoff; the shipped selector instead does full bounded subset enumeration
  (`HEDGE_MAX_CANDIDATES`) with monotone-infeasibility pruning and expected-score selection. Both
  approaches ship a valid schedule; the conformal cutoff would only change *which* candidates are
  considered, and its coverage guarantee would not transfer to unseen hidden notes regardless.
- **The measured hedge premium is a worst-case bound**, built from synthetic maximal disagreement.
  In service the premium is zero whenever the K-sample ensemble agrees, which is the common case.
- **Free-tier provider quota is shared and finite.** Sustained testing during development
  triggered real 429s on both the primary and fallback provider; the service always degraded to a
  controlled `provider_failure` 500 rather than fabricating a plan, but a judge hitting the
  deployed endpoint during a quota-exhausted window would see a 500. The deployed judge-facing key
  should carry adequate quota headroom for a single ten-case run plus normal probing.
- **The ε-slack-maximal re-solve and dual-attribution summary are best-effort refinements.** If
  either is disabled, the service still returns a fully valid, replay-verified schedule — just
  without the extra numeric margin or the per-note marginal-cost breakdown in `plan_summary`.

## Secret-handling policy

`.env` is git-ignored and must never be committed, pasted into an issue, a prompt, a log line, or
an API response. `Settings.describe()` (`app/config.py`) reports only whether a key is *present*,
never its value, and that is all that reaches the startup log. Every `GridWiseError` message is
operator-safe: no stack trace, no key, no raw provider response body. The Docker image is built
with no baked-in secrets; credentials are supplied at container-run / Container-Apps-secret time
only.

---

# Appendix — team development notes

Everything above is the judge-facing submission. The rest of this file is our own
pre-round environment setup and two-person workflow, kept for reproducibility on our
machines. Judges do not need any of it; the quickstart above is self-contained.

The deployment runbook is in [deploy/azure.md](deploy/azure.md).

## Cross-platform environment setup (Linux + macOS)

## 0. Who is on what

| | Machine | Handle | Branch |
|---|---|---|---|
| **Siyam** | Linux, NVIDIA RTX 5060 Ti 16 GB | `siyam` | `feat/lang-api` |
| **Daddy** | macOS (Apple Silicon or Intel) | `daddy` | `feat/energy-verify` |

Both branches cut from `main` and merge back into `main`. Neither machine needs the other's
hardware: every module ships with a stub for its dependency, so both halves run and test alone.

---

## 1. Install the toolchain

### 1.1 Miniforge (conda) — both machines

Miniforge is used rather than Anaconda: conda-forge only, no licence question, same on both OSes.

**Linux (Siyam)**
```bash
curl -fsSLo /tmp/miniforge.sh https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
bash /tmp/miniforge.sh -b -p "$HOME/miniforge3"
"$HOME/miniforge3/bin/conda" init bash
exec bash
```

**macOS (Daddy)** — Apple Silicon is `arm64`; on an Intel Mac swap `arm64` for `x86_64`.
```bash
curl -fsSLo /tmp/miniforge.sh https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-arm64.sh
bash /tmp/miniforge.sh -b -p "$HOME/miniforge3"
"$HOME/miniforge3/bin/conda" init zsh
exec zsh
```

Already have conda or mamba? Skip this. Check with `conda --version` (need ≥ 23).

### 1.2 Git, Docker, curl, jq

**Linux (Siyam)**
```bash
sudo apt-get update
sudo apt-get install -y git curl jq make
# Docker Engine — needed for Gate 6 (image build + push). Siyam only.
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"   # log out and back in for this to take effect
docker run --rm hello-world
```

**macOS (Daddy)**
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install git curl jq make
# Docker Desktop is OPTIONAL for Daddy — Siyam owns the image. Install only if you want it:
# brew install --cask docker
```

### 1.3 Azure CLI — Siyam only, needed at Gate 6

```bash
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
az version
az login          # do this BEFORE the round; do not burn round time on a browser login
az extension add --name containerapp --upgrade
```

Daddy does not need `az`.

---

## 2. Create the conda environment — both machines

```bash
git clone https://github.com/Morningstaaar36/gridwise-llm-energy-optimizer.git
cd gridwise-llm-energy-optimizer

conda env create -f environment.yml
conda activate gridwise
```

If the environment already exists and you are picking up a change:
```bash
conda env update -f environment.yml --prune
```

`environment.yml` installs Python 3.11, NumPy and SciPy from conda-forge (SciPy carries the HiGHS
solver), then pulls every pure-Python dependency from `requirements.txt` so the Docker image and
the local environment share one dependency list.

> **Do not use the system Python.** Both machines ship a Python that is either too new or
> externally managed; `pip install` into it will fail with PEP 668 or produce wheels that do not
> match the Docker image.

---

## 3. Configure secrets

```bash
cp .env.example .env
```

Open `.env` and set at minimum:

| Variable | Value |
|---|---|
| `LLM_BASE_URL` | Provider's OpenAI-compatible base URL. See the comments in `.env.example`. |
| `LLM_API_KEY` | Your key. |
| `LLM_MODEL` | Model id. |

Every supported provider speaks the OpenAI chat-completions protocol, so there is one adapter and
no provider-specific code. `.env` is in `.gitignore` — **never commit it, never paste a key into
an issue, a prompt, a log line, or an API response.**

Daddy can leave `LLM_API_KEY` empty: every task on the `feat/energy-verify` branch runs against
`fixtures/stub_interpretation.json` and needs no model at all.

---

## 4. Optional: local model on Siyam's GPU

The RTX 5060 Ti (16 GB, Blackwell) can serve the fallback model locally. This is for **offline
development and provider-outage backup** — the judge's traffic hits the hosted model through the
deployed endpoint, not this machine.

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:8b
ollama serve &                  # OpenAI-compatible at http://localhost:11434/v1
curl -s http://localhost:11434/v1/models | jq '.data[].id'
```

Ollama already matches the `LLM_FALLBACK_*` block in `.env.example`, so nothing else changes.

Only if Ollama's measured latency is too high, install vLLM instead — **Linux + NVIDIA only**:
```bash
pip install -r requirements-gpu.txt --extra-index-url https://download.pytorch.org/whl/cu128
```
Blackwell (`sm_120`) needs CUDA 12.8 wheels; older PyTorch builds will not run on this card.
**Daddy must never install `requirements-gpu.txt`** — macOS has no CUDA and the install fails.

---

## 5. Verify the environment

Run on **both** machines. Everything here works with no API key and no GPU.

```bash
conda activate gridwise
make verify-env
```

Expected, on both Linux and macOS:

```
python 3.11.x
numpy 2.x.x
scipy 1.1x.x
fastapi 0.11x.x
pydantic 2.x.x
schemas+fixtures parse OK
...
10/10 cases: LP optimum == published reference cost AND reference plan replays clean
```

That last line is the real check: it proves SciPy's HiGHS reproduces all ten published reference
optima to 0.0000 BDT on your machine. If it prints anything else, stop and fix the environment
before the round — do not start Gate 1 on a broken solver.

Already validated on Linux while this scaffold was written, so a mismatch means your machine, not the pins:

| | conda (linux-64) | Docker image (linux/amd64) |
|---|---|---|
| python | 3.11.16 | 3.11.16 |
| numpy | 2.4.6 | 2.4.6 |
| scipy | 1.17.1 | 1.17.1 |
| fastapi / pydantic / openai | — | 0.141.1 / 2.13.5 / 1.109.1 |

The conda environment and the image resolve to the same NumPy and SciPy, so a plan computed
locally and a plan computed in the container come out identical. `docker build` was run end to
end; `environment.yml` was solved with `--dry-run`. **macOS was not verifiable from here — Daddy
runs sections 2 and 5 before the round and reports any drift.**

### Setup is done

Freeze the dependency set so both machines and the image agree:

```bash
make lock        # writes requirements.lock.txt
```

Run `make lock` on **Linux** and commit that file; it is the one the Docker image will use.
Daddy runs `make lock` too and compares — any package that differs in major/minor version gets
resolved before the round, not during it.

That completes the environment setup.

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `conda env create` hangs on solving | classic solver | `conda install -n base conda-libmamba-solver` then `conda config --set solver libmamba` |
| `externally-managed-environment` on pip | you are in the system Python | `conda activate gridwise` first |
| `scipy` import error on macOS arm64 | pip wheel shadowing the conda build | `pip uninstall scipy numpy` then `conda env update -f environment.yml --prune` |
| `make: command not found` on macOS | Xcode CLT missing | `xcode-select --install` |
| `permission denied` on `docker` (Linux) | user not in the docker group yet | log out and back in, or `newgrp docker` |
| `make verify-env` LP costs differ | wrong SciPy/HiGHS | print `scipy.__version__`; must be ≥ 1.14 from conda-forge |
| Ollama returns 404 on `/v1/...` | old build | `ollama --version` ≥ 0.4, then restart `ollama serve` |

# GridWise — environment setup

BUP CSE Fest 2026 · Online Preliminary · LLM-assisted operator-directive interpretation.

**This file covers environment creation only.** Do the whole of it **before the round opens**,
on both machines, and stop at the "Setup is done" checkpoint.

| Document | Read it for |
|---|---|
| **README.md** (this file) | Getting a working environment on Linux and macOS. Nothing else. |
| **[TASKS.md](TASKS.md)** | Who builds what, in what order, on which branch, with acceptance gates. **This is the file to follow during the round.** |
| [docs/ARCHITECTURE_CLAMP.md](docs/ARCHITECTURE_CLAMP.md) | Why the system is shaped the way it is. Reference. |
| [docs/RESEARCH_LINKS.md](docs/RESEARCH_LINKS.md) | Papers, repos, models. Reference, and source material for the video. |
| [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Earlier long-form plan. Superseded in part — see its header note. |

At **Gate 7** this file gets *extended* (not replaced) with the judge-facing quickstart, because
Documentation & Local Reproducibility is worth 10 points. Until then it is setup only.

---

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
git clone <REPO_URL> gridwise-llm-energy-optimizer
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

Now go to **[TASKS.md](TASKS.md)**. Do not start Gate 1 until the round opens.

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

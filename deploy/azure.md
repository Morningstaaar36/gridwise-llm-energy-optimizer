# GridWise — Azure Container Apps deployment

Deploys the exact image published in Gate 6 (`ghcr.io/morningstaaar36/gridwise:v1.0`,
digest `sha256:71da3c80494b4b5567e3a6f007c1b4238688d489ea0208e7391cb75c9412c90a`) so the
registry artifact and the live endpoint are provably the same build.

## Live endpoint

```
https://gridwise.mangowater-ca3ac31c.southeastasia.azurecontainerapps.io
```

- `GET /health` → `{"status":"ok"}`
- `POST /optimize-energy` → verified 10/10 against every public case, see
  `evals/reports/public_cases_20260918_221601.json`

No login, no VPN, no allowlisting — reachable from any network.

## Prerequisites

- `az` CLI logged in (`az login`), subscription with quota for Container Apps
- The image pushed to GHCR (Gate 6 S6.1)
- A GitHub PAT with `write:packages` (`read:packages` is implied) — needed **only** because the
  GHCR package is currently private; see the note at the bottom

## Exact commands used

```bash
az group create -n gridwise-rg -l southeastasia

# Container Apps needs Microsoft.OperationalInsights and Microsoft.App registered on the
# subscription. A fresh subscription usually needs this once:
az provider register -n Microsoft.OperationalInsights --wait
az provider register -n Microsoft.App --wait

az containerapp env create -n gridwise-env -g gridwise-rg -l southeastasia

az containerapp create \
  -n gridwise -g gridwise-rg --environment gridwise-env \
  --image ghcr.io/morningstaaar36/gridwise:v1.0 \
  --target-port 8000 --ingress external \
  --min-replicas 1 --max-replicas 3 \
  --registry-server ghcr.io \
  --registry-username Morningstaaar36 \
  --registry-password "$GH_PAT" \
  --secrets "llm-key=$LLM_API_KEY" "llm-fallback-key=$LLM_FALLBACK_API_KEY" \
  --env-vars \
    "LLM_API_KEY=secretref:llm-key" \
    "LLM_BASE_URL=$LLM_BASE_URL" \
    "LLM_MODEL=$LLM_MODEL" \
    "LLM_FALLBACK_API_KEY=secretref:llm-fallback-key" \
    "LLM_FALLBACK_BASE_URL=$LLM_FALLBACK_BASE_URL" \
    "LLM_FALLBACK_MODEL=$LLM_FALLBACK_MODEL" \
    "LLM_SAMPLES=$LLM_SAMPLES" \
    "HEDGE_ENABLED=$HEDGE_ENABLED" \
    "PORT=8000"

az containerapp show -n gridwise -g gridwise-rg \
  --query properties.configuration.ingress.fqdn -o tsv
```

`$LLM_API_KEY`, `$LLM_BASE_URL`, etc. are read from a local `.env` (see `.env.example` for the
exact names) and never appear in this file, shell history that gets committed, or the image.

**`--min-replicas 1` is required, not optional.** Container Apps scales to zero by default; a
cold start from zero can exceed the judge harness's 60-second readiness window. Do not remove it.

## Why `--registry-server`/`--registry-username`/`--registry-password` are here

The GHCR package (`ghcr.io/morningstaaar36/gridwise`) is currently **private** — new GHCR
packages default to private, and changing visibility via the API needs the `delete:packages`
token scope, which the deployment token does not have. Azure can still pull a private image
directly by authenticating as a registry credential, exactly as above, so this does not block
deployment.

**This does not satisfy the separate "judges can `docker pull` without credentials" requirement**
for the fallback image submission — that needs the GHCR package visibility flipped to public,
which takes two clicks at
`https://github.com/users/Morningstaaar36/packages/container/package/gridwise` → Package
settings → Danger Zone → Change visibility → Public. Do this before final submission even though
it is not required for the Azure deployment above to work.

## Secrets

- `az containerapp create` stores `LLM_API_KEY` and `LLM_FALLBACK_API_KEY` as Container Apps
  secrets (`llm-key`, `llm-fallback-key`), referenced by environment variables via `secretref:`.
  Neither value is ever baked into the image or visible in `az containerapp show` output.
- The registry password (GitHub PAT) is likewise stored as an auto-generated Container Apps
  secret (`ghcrio-morningstaaar36`), not passed as a plain environment variable.
- Rotate the GitHub PAT after the event; it currently has `write:packages` and `repo` scope.

## Verify independently (D6.1)

From a different network than the one used to deploy (phone hotspot, different Wi-Fi):

```bash
./deploy/smoke.sh gridwise.mangowater-ca3ac31c.southeastasia.azurecontainerapps.io
```

Then, from this repository, all ten public cases against the live URL:

```bash
python evals/run_public.py --base-url https://gridwise.mangowater-ca3ac31c.southeastasia.azurecontainerapps.io
```

Expect `10/10 valid | 10/10 interpretation correct | 10/10 replay clean`.

## Redeploying after a change

```bash
docker build --platform linux/amd64 -t ghcr.io/morningstaaar36/gridwise:v1.0 .
docker push ghcr.io/morningstaaar36/gridwise:v1.0
az containerapp update -n gridwise -g gridwise-rg --image ghcr.io/morningstaaar36/gridwise:v1.0
```

`az containerapp update` triggers a new revision from the same tag; Container Apps pulls the
tag fresh (it is not cached against the old digest).

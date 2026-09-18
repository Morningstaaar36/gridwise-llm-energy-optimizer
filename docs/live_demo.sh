#!/usr/bin/env bash
# GridWise video — the one live beat (2:05-2:40 in VIDEO_SCRIPT.md).
# Run this ON CAMERA against the real deployed endpoint. It prints a
# narratable, labeled log to the screen AND saves it to a timestamped file
# so you have a transcript to read from / cite afterward.
#
# Usage: ./docs/live_demo.sh
# Requires: jq, run from the repo root, gridwise conda env active (only so
# fixtures/public_cases.json is readable locally -- the actual API calls go
# out over the network to Azure, no local server needed).

set -euo pipefail

FQDN="gridwise.mangowater-ca3ac31c.southeastasia.azurecontainerapps.io"
BASE_URL="https://$FQDN"
LOG="/tmp/gridwise_live_demo_$(date +%Y%m%d_%H%M%S).log"

exec > >(tee "$LOG") 2>&1

echo "=================================================================="
echo "GridWise live demo -- $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "target: $BASE_URL"
echo "log:    $LOG"
echo "=================================================================="
echo

echo "--- 1) Health check --------------------------------------------"
curl -fsS "$BASE_URL/health"
echo
echo

echo "--- 2) SAMPLE-06 as published (solar cut to ~half, 10 AM-noon) --"
curl -s -X POST "$BASE_URL/optimize-energy" \
  -H "Content-Type: application/json" \
  -d "$(jq '.cases[5].input' fixtures/public_cases.json)" \
  | tee /tmp/gridwise_demo_original.json \
  | jq '{total_cost_bdt, hour10: .hourly_plan[10], hour11: .hourly_plan[11]}'
echo

echo "--- 3) Same note, harsher reading (solar cut to ~10%, not ~50%) -"
jq '.cases[5].input | .operator_notes[0] =
  "Cloud cover during panel inspection will leave only about 10 percent of forecast solar output from 10 AM until noon."' \
  fixtures/public_cases.json > /tmp/gridwise_demo_changed_input.json

curl -s -X POST "$BASE_URL/optimize-energy" \
  -H "Content-Type: application/json" \
  -d @/tmp/gridwise_demo_changed_input.json \
  | tee /tmp/gridwise_demo_changed.json \
  | jq '{total_cost_bdt, hour10: .hourly_plan[10], hour11: .hourly_plan[11]}'
echo

echo "--- 4) Side-by-side: what changed -------------------------------"
python3 - << 'PYEOF'
import json

before = json.load(open("/tmp/gridwise_demo_original.json"))
after = json.load(open("/tmp/gridwise_demo_changed.json"))

b10, a10 = before["hourly_plan"][10], after["hourly_plan"][10]
print(f"{'':16} {'BEFORE (factor 0.5)':>22} {'AFTER (factor 0.1)':>22}")
print(f"{'hour 10 solar_kwh':16} {b10['solar_used_kwh']:>22.2f} {a10['solar_used_kwh']:>22.2f}")
print(f"{'hour 10 grid_kwh':16} {b10['grid_kwh']:>22.2f} {a10['grid_kwh']:>22.2f}")
print(f"{'total_cost_bdt':16} {before['total_cost_bdt']:>22.2f} {after['total_cost_bdt']:>22.2f}")
delta = after["total_cost_bdt"] - before["total_cost_bdt"]
pct = 100 * delta / before["total_cost_bdt"]
print(f"\ndelta: {delta:+.2f} BDT ({pct:+.2f}%) -- from changing one phrase in one note.")
PYEOF
echo
echo "=================================================================="
echo "done. full transcript saved at: $LOG"
echo "=================================================================="

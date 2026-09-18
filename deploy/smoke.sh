#!/usr/bin/env bash
# G6 S6.2 accept check: run this from a network OTHER than the one used to
# deploy (phone hotspot, different Wi-Fi) to prove the endpoint needs no
# login, no VPN, no allowlisting -- exactly what the judge harness gets.
#
# Usage: ./deploy/smoke.sh <fqdn-or-url>
#   ./deploy/smoke.sh gridwise.mangowater-ca3ac31c.southeastasia.azurecontainerapps.io
#   ./deploy/smoke.sh https://gridwise.mangowater-ca3ac31c.southeastasia.azurecontainerapps.io

set -euo pipefail

if [ -z "${1:-}" ]; then
  echo "usage: $0 <fqdn-or-url>" >&2
  exit 2
fi

TARGET="$1"
case "$TARGET" in
  http://*|https://*) BASE_URL="$TARGET" ;;
  *) BASE_URL="https://$TARGET" ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
SAMPLE_INPUT=$(python3 -c "
import json
case = json.load(open('$REPO_ROOT/fixtures/public_cases.json'))['cases'][0]
print(json.dumps(case['input']))
")

echo "=== GET $BASE_URL/health ==="
HEALTH_CODE=$(curl -sS -o /tmp/gridwise_smoke_health.json -w "%{http_code}" --max-time 15 "$BASE_URL/health")
cat /tmp/gridwise_smoke_health.json
echo
if [ "$HEALTH_CODE" != "200" ]; then
  echo "FAIL: expected HTTP 200, got $HEALTH_CODE" >&2
  exit 1
fi
if ! grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' /tmp/gridwise_smoke_health.json; then
  echo "FAIL: health body did not contain status=ok" >&2
  exit 1
fi
echo "PASS: health check"
echo

echo "=== POST $BASE_URL/optimize-energy (SAMPLE-01) ==="
SAMPLE_CODE=$(curl -sS -o /tmp/gridwise_smoke_sample.json -w "%{http_code}" --max-time 35 \
  -X POST "$BASE_URL/optimize-energy" \
  -H "Content-Type: application/json" \
  -d "$SAMPLE_INPUT")
python3 -m json.tool /tmp/gridwise_smoke_sample.json | head -25
if [ "$SAMPLE_CODE" != "200" ]; then
  echo "FAIL: expected HTTP 200, got $SAMPLE_CODE" >&2
  exit 1
fi
echo "PASS: sample request returned a plan"
echo

echo "=== all checks passed against $BASE_URL ==="
echo "reachable with no login, no VPN, no allowlisting required."

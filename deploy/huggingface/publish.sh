#!/usr/bin/env bash
# Publish the live demo (the dashboard exported as one HTML file) as a static Hugging Face Space. Static Spaces are free;
# Docker Spaces need a PRO subscription.
# Usage: HF_TOKEN=<write token> deploy/huggingface/publish.sh [owner/space-name]
set -euo pipefail

SPACE="${1:-senanurcetin/gs-quant-risk}"
: "${HF_TOKEN:?Set HF_TOKEN to a Hugging Face token with write access}"

ROOT="$(git rev-parse --show-toplevel)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Create the Space when it does not exist yet (HTTP 409 means it already does); public unless HF_PRIVATE=true
RESPONSE="$(curl -sS -w '\n%{http_code}' -X POST https://huggingface.co/api/repos/create \
  -H "Authorization: Bearer ${HF_TOKEN}" -H 'Content-Type: application/json' \
  -d "{\"type\":\"space\",\"sdk\":\"static\",\"name\":\"${SPACE#*/}\",\"organization\":\"${SPACE%%/*}\",\"private\":${HF_PRIVATE:-false}}")"
STATUS="${RESPONSE##*$'\n'}"
if [ "$STATUS" != "200" ] && [ "$STATUS" != "409" ]; then
  echo "Creating the Space failed (HTTP $STATUS): ${RESPONSE%$'\n'*}" >&2
  exit 1
fi

# The page is built from this checkout, so the Space shows the code that is committed here
cd "$ROOT"
python3 -m gs_quant.apps.risk_dashboard export -o "$WORK/index.html"
test "$(wc -c < "$WORK/index.html")" -gt 500000
cp deploy/huggingface/README.md "$WORK/README.md"

cd "$WORK"
git init -q -b main
git add -A
git -c user.name="${GIT_AUTHOR_NAME:-publish}" -c user.email="${GIT_AUTHOR_EMAIL:-publish@localhost}" commit -q -m "Publish $(git -C "$ROOT" rev-parse --short HEAD)"
git push --force "https://senanurcetin:${HF_TOKEN}@huggingface.co/spaces/${SPACE}" main
echo "https://huggingface.co/spaces/${SPACE}"

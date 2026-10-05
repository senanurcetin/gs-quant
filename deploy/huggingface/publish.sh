#!/usr/bin/env bash
# Publish the application as a Docker Space.
# Usage: HF_TOKEN=<write token> deploy/huggingface/publish.sh [owner/space-name]
set -euo pipefail

SPACE="${1:-senanurcetin/gs-quant-risk}"
: "${HF_TOKEN:?Set HF_TOKEN to a Hugging Face token with write access}"

# Create the Space when it does not exist yet (HTTP 409 means it already does); public unless HF_PRIVATE=true
RESPONSE="$(curl -sS -w '\n%{http_code}' -X POST https://huggingface.co/api/repos/create \
  -H "Authorization: Bearer ${HF_TOKEN}" -H 'Content-Type: application/json' \
  -d "{\"type\":\"space\",\"sdk\":\"docker\",\"name\":\"${SPACE#*/}\",\"organization\":\"${SPACE%%/*}\",\"private\":${HF_PRIVATE:-false}}")"
STATUS="${RESPONSE##*$'\n'}"
if [ "$STATUS" != "200" ] && [ "$STATUS" != "409" ]; then
  echo "Creating the Space failed (HTTP $STATUS): ${RESPONSE%$'\n'*}" >&2
  exit 1
fi

ROOT="$(git rev-parse --show-toplevel)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# A Space needs its own README.md (the card) at the root; the repository's README stays untouched.
git -C "$ROOT" archive HEAD | tar -x -C "$WORK"
cp "$ROOT/deploy/huggingface/README.md" "$WORK/README.md"

cd "$WORK"
git init -q -b main
git add -A
git -c user.name="${GIT_AUTHOR_NAME:-publish}" -c user.email="${GIT_AUTHOR_EMAIL:-publish@localhost}" commit -q -m "Publish $(git -C "$ROOT" rev-parse --short HEAD)"
git push --force "https://senanurcetin:${HF_TOKEN}@huggingface.co/spaces/${SPACE}" main
echo "https://huggingface.co/spaces/${SPACE}"

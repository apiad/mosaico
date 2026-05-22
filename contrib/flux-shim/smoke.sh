#!/usr/bin/env bash
# smoke test against a running flux-shim. Posts a single text-only request,
# decodes the response image to smoke.png, asserts non-zero size.
set -euo pipefail

HOST="${FLUX_SHIM_HOST:-localhost}"
PORT="${FLUX_SHIM_PORT:-8000}"
URL="http://${HOST}:${PORT}/v1/chat/completions"

echo "[smoke] POST ${URL}"

RESP=$(curl -s -X POST "${URL}" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "flux-2-klein-4b",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "a heron at dawn, watercolor sketch"}
        ]}],
        "size": "1024x1024"
    }')

URL_FIELD=$(echo "$RESP" | python3 -c "import sys, json; print(json.load(sys.stdin)['choices'][0]['message']['images'][0]['image_url']['url'])")

if [[ ! "$URL_FIELD" =~ ^data:image/png\;base64, ]]; then
    echo "[smoke] FAIL: unexpected response shape"
    echo "$RESP" | head -c 500
    exit 1
fi

echo "$URL_FIELD" | cut -d, -f2 | base64 -d > smoke.png
SIZE=$(stat -c%s smoke.png 2>/dev/null || stat -f%z smoke.png)
echo "[smoke] OK: wrote smoke.png (${SIZE} bytes)"
test "$SIZE" -gt 1000 || { echo "[smoke] FAIL: image too small"; exit 1; }

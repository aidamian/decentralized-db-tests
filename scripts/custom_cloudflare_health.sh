#!/bin/sh
set -eu

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

python - <<'PY'
import json
import os
import urllib.error
import urllib.request

results = []
for index in range(1, 4):
    raw = os.environ.get(f"CLOUDFLARE_URL_{index}", "").rstrip("/")
    if not raw:
        results.append({"index": index, "error": "missing CLOUDFLARE_URL"})
        continue
    base = raw if raw.startswith(("http://", "https://")) else "https://" + raw
    try:
        with urllib.request.urlopen(base + "/health", timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
            results.append(
                {
                    "index": index,
                    "status": response.status,
                    "node_id": payload.get("node_id"),
                    "ok": payload.get("ok"),
                }
            )
    except urllib.error.HTTPError as exc:
        headers = {key.lower(): value for key, value in exc.headers.items()}
        results.append(
            {
                "index": index,
                "status": exc.code,
                "server": headers.get("server"),
                "cf_ray": headers.get("cf-ray"),
                "content_type": headers.get("content-type"),
            }
        )
    except Exception as exc:
        results.append({"index": index, "error": f"{type(exc).__name__}: {exc}"})
print(json.dumps(results, sort_keys=True))
PY

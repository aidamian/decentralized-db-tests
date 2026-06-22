#!/bin/sh
set -eu

python -m custom.node.server &
server_pid=$!

shutdown() {
  kill "$server_pid" 2>/dev/null || true
  if [ "${cloudflared_pid:-}" ]; then
    kill "$cloudflared_pid" 2>/dev/null || true
  fi
}

trap shutdown INT TERM EXIT

if [ "${ENABLE_CLOUDFLARED:-0}" = "1" ]; then
  token_file="${CLOUDFLARED_TOKEN_FILE:-/run/secrets/cf_token}"
  origin_url="${CLOUDFLARED_ORIGIN_URL:-http://127.0.0.1:${PORT:-8080}}"
  if [ ! -s "$token_file" ]; then
    echo "cloudflared token file is missing or empty: $token_file" >&2
    exit 64
  fi
  cloudflared tunnel --no-autoupdate run --token-file "$token_file" --url "$origin_url" &
  cloudflared_pid=$!
fi

while :; do
  if ! kill -0 "$server_pid" 2>/dev/null; then
    wait "$server_pid"
    exit $?
  fi
  if [ "${cloudflared_pid:-}" ] && ! kill -0 "$cloudflared_pid" 2>/dev/null; then
    wait "$cloudflared_pid"
    exit $?
  fi
  sleep 1
done

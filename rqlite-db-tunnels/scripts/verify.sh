#!/usr/bin/env sh
set -eu

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
compose="$project_dir/compose.yaml"

fail() {
  printf '%s\n' "rqlite-db-tunnels verify failed: $*" >&2
  exit 1
}

grep -q 'rqlite/rqlite' "$compose" || fail "missing rqlite engine"
grep -q 'cloudflared-external' "$compose" || fail "missing external Cloudflare tunnel"
grep -q 'CLOUDFLARE_TOKEN_EXTERNAL' "$compose" || fail "missing external tunnel token"
for index in 1 2 3; do
  grep -q "CLOUDFLARE_TOKEN_${index}" "$compose" || fail "missing node ${index} token"
  grep -q "CLOUDFLARE_URL_${index}" "$compose" || fail "missing node ${index} URL"
done
! grep -q '^  ports:' "$compose" || fail "host port forwarding is forbidden"
grep -q 'cloudflared access tcp' "$compose" || fail "missing Cloudflare TCP peer overlay"
grep -q -- '-join' "$compose" || fail "tunnel variant should exercise native rqlite join over tunnel proxies"

printf '%s\n' "rqlite-db-tunnels static checks passed"

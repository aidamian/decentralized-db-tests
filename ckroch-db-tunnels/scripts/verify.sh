#!/usr/bin/env sh
set -eu

# Static guardrails for the native Cockroach tunnel experiment. The expected
# inter-node RPC path is Cloudflare TCP proxying, not Docker peer networking.
project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
compose="$project_dir/compose.yaml"

fail() {
  printf '%s\n' "ckroch-db-tunnels verify failed: $*" >&2
  exit 1
}

grep -q 'cockroachdb/cockroach' "$compose" || fail "missing CockroachDB engine"
grep -q 'cloudflared-external' "$compose" || fail "missing external Cloudflare tunnel"
grep -q 'CLOUDFLARE_TOKEN_EXTERNAL' "$compose" || fail "missing external tunnel token"
for index in 1 2 3; do
  grep -q "CLOUDFLARE_TOKEN_${index}" "$compose" || fail "missing node ${index} token"
  grep -q "CLOUDFLARE_URL_${index}" "$compose" || fail "missing node ${index} URL"
done
! grep -q '^  ports:' "$compose" || fail "host port forwarding is forbidden"
grep -q 'cloudflared access tcp' "$compose" || fail "missing Cloudflare TCP peer overlay"
grep -q -- '--join=ckroch1-peer' "$compose" || fail "tunnel variant should exercise native Cockroach join over tunnel proxies"
grep -q 'cockroach init' "$compose" || fail "missing Cockroach cluster init service"
grep -q '../_volumes/ckroch-db-tunnels/worker1' "$compose" || fail "missing per-lab worker1 bind mount"
grep -q 'persistence-client' "$compose" || fail "missing persistence client service"
[ -f "$project_dir/scripts/persistence_check.py" ] || fail "missing persistence check script"

printf '%s\n' "ckroch-db-tunnels static checks passed"

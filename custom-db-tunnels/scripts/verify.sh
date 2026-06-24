#!/usr/bin/env sh
set -eu

# Static guardrails for the custom tunnel lab. Direct node access is represented
# only by Cloudflare sidecars, never by shared Docker networks or host ports.
project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
compose="$project_dir/compose.yaml"

fail() {
  printf '%s\n' "custom-db-tunnels verify failed: $*" >&2
  exit 1
}

grep -q 'cloudflared-external' "$compose" || fail "missing external Cloudflare tunnel"
grep -q 'CLOUDFLARE_TOKEN_EXTERNAL' "$compose" || fail "missing external tunnel token"
grep -q 'CLOUDFLARE_URL_EXTERNAL' "$compose" || fail "missing external tunnel URL"
for index in 1 2 3; do
  grep -q "CLOUDFLARE_TOKEN_${index}" "$compose" || fail "missing node ${index} token"
  grep -q "CLOUDFLARE_URL_${index}" "$compose" || fail "missing node ${index} URL"
done
! grep -q '^  ports:' "$compose" || fail "host port forwarding is forbidden"
grep -q 'network_mode: "service:custom-node1"' "$compose" || fail "node1 tunnel must share only node1 namespace"
grep -q 'network_mode: "service:custom-node2"' "$compose" || fail "node2 tunnel must share only node2 namespace"
grep -q 'network_mode: "service:custom-node3"' "$compose" || fail "node3 tunnel must share only node3 namespace"
grep -q '../_volumes/custom-db-tunnels/worker1' "$compose" || fail "missing per-lab worker1 bind mount"
grep -q 'persistence-client' "$compose" || fail "missing persistence client service"
[ -f "$project_dir/scripts/persistence_check.py" ] || fail "missing persistence check script"

printf '%s\n' "custom-db-tunnels static checks passed"

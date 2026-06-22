#!/usr/bin/env sh
set -eu

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

printf '%s\n' "custom-db-tunnels static checks passed"

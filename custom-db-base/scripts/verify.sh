#!/usr/bin/env sh
set -eu

# Static guardrails for the brokered custom base lab. These checks do not prove
# runtime replication; they prove the compose file keeps DB nodes isolated and
# keeps client ingress behind the external Cloudflare tunnel.
project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
compose="$project_dir/compose.yaml"

fail() {
  printf '%s\n' "custom-db-base verify failed: $*" >&2
  exit 1
}

grep -q 'event-bus' "$compose" || fail "missing NATS event-bus"
grep -q 'cloudflared-external' "$compose" || fail "missing external Cloudflare tunnel"
grep -q 'CLOUDFLARE_TOKEN_EXTERNAL' "$compose" || fail "missing external tunnel token"
! grep -q '^  ports:' "$compose" || fail "host port forwarding is forbidden"
grep -q 'node1_net' "$compose" || fail "missing isolated node1 network"
grep -q 'node2_net' "$compose" || fail "missing isolated node2 network"
grep -q 'node3_net' "$compose" || fail "missing isolated node3 network"
grep -q 'ENGINE: custom' "$compose" || fail "missing custom relay engine"

printf '%s\n' "custom-db-base static checks passed"

#!/usr/bin/env sh
set -eu

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
compose="$project_dir/compose.yaml"

fail() {
  printf '%s\n' "ckroch-db-base verify failed: $*" >&2
  exit 1
}

grep -q 'cockroachdb/cockroach' "$compose" || fail "missing CockroachDB engine"
grep -q 'start-single-node' "$compose" || fail "base Cockroach should use isolated single-node stores"
grep -q 'event-bus' "$compose" || fail "missing NATS event-bus"
grep -q 'cloudflared-external' "$compose" || fail "missing external Cloudflare tunnel"
grep -q 'CLOUDFLARE_TOKEN_EXTERNAL' "$compose" || fail "missing external tunnel token"
! grep -q '^  ports:' "$compose" || fail "host port forwarding is forbidden"
! grep -q -- '--listen-addr' "$compose" || fail "Docker start-single-node must not override listen addr"
! grep -q -- '--join' "$compose" || fail "base Cockroach must not use native peer joins"
grep -q 'node1_net' "$compose" || fail "missing isolated node1 network"
grep -q 'node2_net' "$compose" || fail "missing isolated node2 network"
grep -q 'node3_net' "$compose" || fail "missing isolated node3 network"

printf '%s\n' "ckroch-db-base static checks passed"

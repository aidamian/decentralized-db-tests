#!/usr/bin/env sh
set -eu

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
compose="$project_dir/compose.yaml"

fail() {
  printf '%s\n' "rqlite-db-base verify failed: $*" >&2
  exit 1
}

grep -q 'rqlite/rqlite' "$compose" || fail "missing rqlite engine"
grep -q 'event-bus' "$compose" || fail "missing NATS event-bus"
grep -q 'cloudflared-external' "$compose" || fail "missing external Cloudflare tunnel"
grep -q 'CLOUDFLARE_TOKEN_EXTERNAL' "$compose" || fail "missing external tunnel token"
! grep -q '^  ports:' "$compose" || fail "host port forwarding is forbidden"
! grep -q -- '-join' "$compose" || fail "base rqlite must not use native peer joins"
! grep -q -- '-bootstrap-expect' "$compose" || fail "base rqlite must not bootstrap a native cluster"
grep -q 'node1_net' "$compose" || fail "missing isolated node1 network"
grep -q 'node2_net' "$compose" || fail "missing isolated node2 network"
grep -q 'node3_net' "$compose" || fail "missing isolated node3 network"

printf '%s\n' "rqlite-db-base static checks passed"

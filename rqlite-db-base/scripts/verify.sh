#!/usr/bin/env sh
set -eu

# Static guardrails for the brokered rqlite base lab. Native rqlite join flags
# are forbidden here because this lab uses NATS relays, not Raft peer TCP.
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
grep -q '../_volumes/rqlite-db-base/worker1' "$compose" || fail "missing per-lab worker1 bind mount"
grep -q '../_volumes/rqlite-db-base/bus' "$compose" || fail "missing per-lab bus bind mount"
grep -q 'persistence-client' "$compose" || fail "missing persistence client service"
[ -f "$project_dir/scripts/persistence_check.py" ] || fail "missing persistence check script"

printf '%s\n' "rqlite-db-base static checks passed"

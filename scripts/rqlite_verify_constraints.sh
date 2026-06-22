#!/bin/sh
set -eu

compose_file="${RQLITE_COMPOSE_FILE:-oss-rqlite/compose.yaml}"
compose="docker compose -f $compose_file"

for service in rqlite1 rqlite2 rqlite3; do
  cid=$($compose ps -q "$service")
  if [ -z "$cid" ]; then
    echo "$service is not running" >&2
    exit 1
  fi

  ports=$(docker inspect "$cid" --format '{{json .NetworkSettings.Ports}}')
  python - "$service" "$ports" <<'PY'
import json
import sys

service = sys.argv[1]
ports = json.loads(sys.argv[2])
published = {port: bindings for port, bindings in ports.items() if bindings}
if published:
    print(f"{service} has host-published ports: {published}", file=sys.stderr)
    raise SystemExit(1)
PY

  networks=$(docker inspect "$cid" --format '{{len .NetworkSettings.Networks}}')
  if [ "$networks" != "1" ]; then
    echo "$service should be attached to exactly one Docker network, got $networks" >&2
    exit 1
  fi
done

$compose run --rm rqlite-client wait --min-ready 3 --timeout 90 >/tmp/rqlite-wait.json
$compose run --rm rqlite-client nodes >/tmp/rqlite-nodes.json

echo "rqlite lab constraints verified"
cat /tmp/rqlite-wait.json
cat /tmp/rqlite-nodes.json

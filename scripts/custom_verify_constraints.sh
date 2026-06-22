#!/bin/sh
set -eu

compose_file="${CUSTOM_COMPOSE_FILE:-custom/compose.yaml}"
compose="docker compose -f $compose_file"

for service in custom-node1 custom-node2 custom-node3; do
  cid=$($compose ps -q "$service")
  if [ -z "$cid" ]; then
    echo "$service is not running" >&2
    exit 1
  fi

  ports=$(docker inspect "$cid" --format '{{json .NetworkSettings.Ports}}')
  if [ "$ports" != '{"8080/tcp":null}' ] && [ "$ports" != '{}' ]; then
    echo "$service has host-published ports: $ports" >&2
    exit 1
  fi

  networks=$(docker inspect "$cid" --format '{{len .NetworkSettings.Networks}}')
  if [ "$networks" != "1" ]; then
    echo "$service should be attached to exactly one Docker network, got $networks" >&2
    exit 1
  fi
done

for source in custom-node1 custom-node2 custom-node3; do
  $compose exec -T "$source" python - "$source" <<'PY'
import socket
import sys

source = sys.argv[1]
for host in ("custom-node1", "custom-node2", "custom-node3"):
    if host == source:
        continue
    try:
        socket.create_connection((host, 8080), timeout=2)
    except OSError as exc:
        print(f"blocked {source} -> {host}: {type(exc).__name__}")
    else:
        print(f"unexpected node-to-node connectivity {source} -> {host}", file=sys.stderr)
        raise SystemExit(1)
PY
done

echo "custom lab constraints verified"

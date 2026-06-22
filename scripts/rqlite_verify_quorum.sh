#!/bin/sh
set -eu

compose_file="${RQLITE_COMPOSE_FILE:-oss-rqlite/compose.yaml}"
compose="docker compose -f $compose_file"

$compose run --rm rqlite-client e2e >/tmp/rqlite-e2e.json
$compose stop rqlite3 >/dev/null
$compose run --rm rqlite-client wait --min-ready 2 --timeout 60 >/tmp/rqlite-one-down.json
$compose run --rm rqlite-client execute "INSERT OR REPLACE INTO kv(k, v) VALUES('after_one_down', 'ok')" >/tmp/rqlite-one-down-write.json
$compose stop rqlite2 >/dev/null

if $compose run --rm rqlite-client execute "INSERT OR REPLACE INTO kv(k, v) VALUES('after_two_down', 'fail')" >/tmp/rqlite-two-down-write.json; then
  echo "unexpected rqlite write success with one voter" >&2
  cat /tmp/rqlite-two-down-write.json >&2
  exit 1
fi

echo "rqlite quorum behavior verified"
cat /tmp/rqlite-e2e.json
cat /tmp/rqlite-one-down.json
cat /tmp/rqlite-one-down-write.json
cat /tmp/rqlite-two-down-write.json

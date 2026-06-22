# Decentralized DB Tests

This repo contains two runnable labs for testing database behavior when Docker containers do not publish host ports.

## Tracks

### Custom AP Architecture Test

Path: `custom/`

This is a Python/SQLite prototype for the strict architecture constraint:

- three database node containers
- one persistent SQLite volume per node
- no host port forwarding
- no direct node-to-node Docker routing
- optional Cloudflare Tunnel inside each node container
- client-orchestrated sync through HTTP APIs

The node API stores an append-only event log and a materialized key/value projection. The client creates one logical event on the first reachable node, imports that same event to other reachable nodes, and can sync event logs later. Concurrent independent writes are preserved as conflict metadata.

Expected behavior:

- 3/3 nodes up: writes can be acknowledged by all nodes.
- 2/3 nodes up: writes can still be accepted with `--min-acks 1` or `2`.
- 1/3 node up: writes can still be accepted with `--min-acks 1`.
- Recovered nodes converge after sync.
- No linearizability or SQL transactions are claimed.

Run locally:

```bash
docker compose -f custom/compose.yaml down -v
docker compose -f custom/compose.yaml up -d --build custom-node1 custom-node2 custom-node3
scripts/custom_verify_constraints.sh
docker compose -f custom/compose.yaml run --rm custom-client put alpha '{"count":1}' --min-acks 3
docker compose -f custom/compose.yaml run --rm custom-client get alpha --min-responses 3
docker compose -f custom/compose.yaml stop custom-node2 custom-node3
docker compose -f custom/compose.yaml run --rm custom-client put isolated '"survivor"' --min-acks 1
```

Run with Cloudflare tokens from `.env`:

```bash
set -a
. ./.env
set +a

docker compose -f custom/compose.yaml -f custom/compose.cloudflare.yaml down -v
docker compose -f custom/compose.yaml -f custom/compose.cloudflare.yaml up -d --build custom-node1 custom-node2 custom-node3
```

The containers run:

```bash
cloudflared tunnel --no-autoupdate run --token-file /run/secrets/cf_token_N --url http://127.0.0.1:8080
```

The current `.env` tokens successfully start Cloudflare tunnel connectors, but the prepared public URLs return Cloudflare edge `403 Forbidden`. The connector logs show registered QUIC connections and `url:http://127.0.0.1:8080`, so the remaining issue is Cloudflare hostname/Access/routing configuration, not the container origin.

### OSS Quorum rqlite Test

Path: `oss-rqlite/`

This is the quasi out-of-the-box open-source track. It uses the pinned image `rqlite/rqlite:10.2.1` as a 3-node Raft cluster.

Expected behavior:

- 3/3 nodes up: SQL reads/writes pass.
- 2/3 nodes up: quorum remains; writes pass.
- 1/3 node up: quorum is lost; writes fail with 503/unavailable.

Run locally:

```bash
docker compose -f oss-rqlite/compose.yaml down -v
docker compose -f oss-rqlite/compose.yaml up -d rqlite1 rqlite2 rqlite3
scripts/rqlite_verify_constraints.sh
scripts/rqlite_verify_quorum.sh
```

The quorum script intentionally stops two nodes and expects the final one-voter write to fail.

The local rqlite lab uses one private Docker network for Raft peer traffic. A strict no-direct-routing rqlite deployment requires Cloudflare TCP Access hostnames and noninteractive `cloudflared access tcp` proxies for rqlite's Raft port. See `docs/oss-cloudflare-tcp-overlay.md`.

## Verification

Run all fast unit/file tests:

```bash
python -m unittest \
  tests.test_custom_store \
  tests.test_custom_client \
  tests.test_custom_lab_files \
  tests.test_oss_rqlite_files
```

The repo intentionally uses Python's standard library for the prototype and clients, so no local Python dependency installation is required.

## Research Summary

The council recommendation was:

- Avoid CockroachDB, etcd, dqlite, FoundationDB, and rqlite for the strict AP/no-peer-routing track because native clustering needs peer transport and quorum.
- Use rqlite for the OSS quorum track because the corrected requirement accepts 3-node quorum with one failed node.
- Use a custom event-log AP prototype for the strict no-direct-node-routing test.
- Treat Cloudflare Tunnel as ingress/overlay infrastructure, not as a database consistency mechanism.

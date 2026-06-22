# ckroch-db-base

Use this lab for a CockroachDB-backed brokered logical-replica approach.

```bash
cd ckroch-db-base
./scripts/verify.sh
docker compose config >/tmp/ckroch-db-base.compose.yaml
docker compose up --build -d event-bus ckroch1 ckroch2 ckroch3 relay1 relay2 relay3 gateway
docker compose run --rm client
docker compose down -v
```

Cloudflare client ingress:

```bash
set -a
. ../.env
set +a
docker compose --profile edge up --build -d
```

Design details:

- This is not a native CockroachDB cluster.
- Each CockroachDB instance runs `start-single-node`.
- Relays apply idempotent SQL commands from NATS JetStream.
- Native CockroachDB quorum and replication are reserved for `ckroch-db-tunnels`.

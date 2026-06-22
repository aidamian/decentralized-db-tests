# rqlite-db-base

Use this lab for a rqlite-backed brokered logical-replica approach.

```bash
cd rqlite-db-base
./scripts/verify.sh
docker compose config >/tmp/rqlite-db-base.compose.yaml
docker compose up --build -d event-bus rqlite1 rqlite2 rqlite3 relay1 relay2 relay3 gateway
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

- This is not native rqlite clustering.
- Each rqlite instance is single-node and isolated.
- Relays apply idempotent SQL commands from NATS JetStream.
- There is no `-join` or `-bootstrap-expect` in this base project.

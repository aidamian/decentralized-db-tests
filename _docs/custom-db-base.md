# custom-db-base

Use this lab for the custom AP/event-store implementation with brokered communication.

```bash
cd custom-db-base
./scripts/verify.sh
docker compose config >/tmp/custom-db-base.compose.yaml
docker compose up --build -d event-bus custom-node1 custom-node2 custom-node3 relay1 relay2 relay3 gateway
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

- NATS JetStream carries write commands.
- Relays consume the command stream and apply deterministic events to their local custom node only.
- Custom DB containers do not share networks with each other or with the NATS bus.
- The external tunnel must route to `gateway:8080`.

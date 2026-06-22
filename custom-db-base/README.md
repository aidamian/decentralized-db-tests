# custom-db-base

Brokered custom AP database lab. The three DB node containers never share a Docker network and never connect to each other directly. Each node is paired with a relay sidecar; relays consume commands from NATS JetStream and apply deterministic events to only their local custom node.

Run local static checks:

```bash
./scripts/verify.sh
docker compose config >/tmp/custom-db-base.compose.yaml
```

Run a local brokered e2e without publishing host ports:

```bash
docker compose up --build -d event-bus custom-node1 custom-node2 custom-node3 relay1 relay2 relay3 gateway
docker compose run --rm client
docker compose down -v
```

Run with the external Cloudflare ingress connector:

```bash
set -a
. ../.env
set +a
docker compose --profile edge up --build -d
```

`CLOUDFLARE_TOKEN_EXTERNAL` must point to a remotely managed tunnel whose origin service is the gateway HTTP service. The client-facing URL is `CLOUDFLARE_URL_EXTERNAL`.

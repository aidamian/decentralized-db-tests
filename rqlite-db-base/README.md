# rqlite-db-base

Brokered rqlite lab. This is not native rqlite clustering: native rqlite Raft needs node-to-node TCP. In this base project each rqlite container is an isolated single-node rqlite instance, and a relay sidecar applies the same command stream from NATS JetStream to its local rqlite HTTP API.

Run local static checks:

```bash
./scripts/verify.sh
docker compose config >/tmp/rqlite-db-base.compose.yaml
```

Run a local brokered e2e:

```bash
docker compose up --build -d event-bus rqlite1 rqlite2 rqlite3 relay1 relay2 relay3 gateway
docker compose run --rm client
docker compose down
```

Run with Cloudflare client ingress:

```bash
set -a
. ../.env
set +a
docker compose --profile edge up --build -d
```

`CLOUDFLARE_TOKEN_EXTERNAL` must route to the gateway origin. The rqlite nodes themselves are not published in this base project.

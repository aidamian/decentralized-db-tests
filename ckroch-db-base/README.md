# ckroch-db-base

Brokered CockroachDB lab. This is not a native CockroachDB cluster: native CockroachDB requires peer TCP connectivity and `--join`. Here each CockroachDB container runs `start-single-node` on its own isolated network. A relay sidecar applies the same NATS JetStream command stream to its local SQL endpoint.

Run local static checks:

```bash
./scripts/verify.sh
docker compose config >/tmp/ckroch-db-base.compose.yaml
```

Run a local brokered e2e:

```bash
docker compose up --build -d event-bus ckroch1 ckroch2 ckroch3 relay1 relay2 relay3 gateway
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

`CLOUDFLARE_TOKEN_EXTERNAL` must route to the gateway origin. The CockroachDB SQL and inter-node ports are not published in this base project.

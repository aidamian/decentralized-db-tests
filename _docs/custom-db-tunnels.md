# custom-db-tunnels

Use this lab for the custom DB implementation where the gateway reaches nodes only through Cloudflare node URLs.

```bash
cd custom-db-tunnels
./scripts/verify.sh
set -a
. ../.env
set +a
docker compose config >/tmp/custom-db-tunnels.compose.yaml
docker compose --profile edge up --build -d
```

Design details:

- `cloudflared-node1..3` publish the three local custom nodes.
- The gateway uses `CLOUDFLARE_URL_1..3` as its node URLs.
- `cloudflared-external` publishes only the gateway for client ingress.
- Do not run another tunnel project with the same tokens at the same time.

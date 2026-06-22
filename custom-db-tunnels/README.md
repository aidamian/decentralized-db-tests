# custom-db-tunnels

Custom database tunnel lab. The gateway exposes the client API, and it reaches the three DB nodes only through `CLOUDFLARE_URL_1`, `CLOUDFLARE_URL_2`, and `CLOUDFLARE_URL_3`. Each DB node has an adjacent `cloudflared-nodeN` sidecar sharing that node's network namespace, so the Cloudflare origin is local to that node container.

Run static checks:

```bash
./scripts/verify.sh
docker compose config >/tmp/custom-db-tunnels.compose.yaml
```

Run the tunnel lab:

```bash
set -a
. ../.env
set +a
docker compose --profile edge up --build -d
```

Only one project should run these shared Cloudflare tunnel tokens at a time. The external client URL is `CLOUDFLARE_URL_EXTERNAL`; direct node URLs are for this tunnel experiment and diagnostics only.

# rqlite-db-tunnels

Native rqlite tunnel experiment. This project is the last-resort variant: rqlite Raft still needs TCP, so each peer address is a local `cloudflared access tcp` sidecar that forwards to the remote node's Cloudflare URL. No two rqlite DB containers share a Docker network.

Run static checks:

```bash
./scripts/verify.sh
docker compose config >/tmp/rqlite-db-tunnels.compose.yaml
```

Run the tunnel experiment:

```bash
set -a
. ../.env
set +a
docker compose --profile edge up --build -d
```

Cloudflare prerequisites:

- `CLOUDFLARE_TOKEN_EXTERNAL` routes to the gateway HTTP origin for client ingress.
- `CLOUDFLARE_TOKEN_1..3` route to each rqlite node's Raft TCP origin.
- `CLOUDFLARE_URL_1..3` must be TCP-capable Cloudflare Access hostnames usable by `cloudflared access tcp`.
- Automated TCP Access usually needs service authentication or WARP/private routing, not an interactive browser login.

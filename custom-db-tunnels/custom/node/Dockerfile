FROM cloudflare/cloudflared:latest AS cloudflared

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

COPY --from=cloudflared /usr/local/bin/cloudflared /usr/local/bin/cloudflared
COPY custom /app/custom

RUN chmod +x /app/custom/node/run-node.sh

ENTRYPOINT ["/app/custom/node/run-node.sh"]

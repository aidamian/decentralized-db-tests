FROM python:3.12-slim

# Reuse the official cloudflared binary, but run it through a tiny Python
# wrapper so compose can accept either bare hostnames or full https:// URLs in
# the existing CLOUDFLARE_URL_N variables.
COPY --from=cloudflare/cloudflared:latest /usr/local/bin/cloudflared /usr/local/bin/cloudflared
COPY access/run-access.py /usr/local/bin/run-access.py

ENTRYPOINT ["python", "/usr/local/bin/run-access.py"]

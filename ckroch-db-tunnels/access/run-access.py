from __future__ import annotations

"""Normalize Cloudflare TCP Access hostnames and exec cloudflared.

The lab .env historically stores values named CLOUDFLARE_URL_N. For HTTP labs a
full URL such as https://node1.example.com is fine, but `cloudflared access tcp
--hostname` expects the hostname part only. This wrapper keeps the public .env
contract stable while making the TCP sidecars strict and repeatable.
"""

import os
import urllib.parse


def main() -> None:
    raw_hostname = os.environ["CLOUDFLARE_TARGET_HOSTNAME"].strip()
    listen_url = os.environ["LOCAL_ACCESS_LISTEN"].strip()
    hostname = _normalize_hostname(raw_hostname)
    if not listen_url:
        raise SystemExit("LOCAL_ACCESS_LISTEN must not be empty")

    # cloudflared access tcp connects to a Cloudflare Access hostname and opens
    # a local TCP listener on --url for the database process in this node's
    # private Docker network.
    os.execvp(
        "cloudflared",
        ["cloudflared", "access", "tcp", "--hostname", hostname, "--url", listen_url],
    )


def _normalize_hostname(value: str) -> str:
    if not value:
        raise SystemExit("CLOUDFLARE_TARGET_HOSTNAME must not be empty")
    parsed = urllib.parse.urlparse(value if "://" in value else f"//{value}")
    hostname = parsed.hostname
    if not hostname:
        raise SystemExit(f"invalid Cloudflare hostname: {value!r}")
    if parsed.username or parsed.password:
        raise SystemExit("Cloudflare hostname must not contain credentials")
    if parsed.port:
        return f"{hostname}:{parsed.port}"
    return hostname


if __name__ == "__main__":
    main()

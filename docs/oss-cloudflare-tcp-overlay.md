# rqlite Cloudflare TCP Overlay

The local `oss-rqlite/compose.yaml` lab uses rqlite in its normal out-of-the-box shape: three rqlite nodes share one private Docker network for Raft and HTTP traffic, and no service publishes host ports.

That proves the quorum behavior, but it does not prove the original no-direct-peer-routing constraint. A strict no-direct-routing rqlite deployment needs a TCP overlay for the Raft port, not only the three HTTP Cloudflare URLs.

Required Cloudflare shape:

- One HTTP public hostname per rqlite node for client API access.
- One non-HTTP/TCP Cloudflare Access application per rqlite node for Raft traffic.
- A noninteractive `cloudflared access tcp` process inside each node container for every peer Raft endpoint.
- rqlite `-raft-adv-addr` values pointing at the local `cloudflared access tcp` listener ports.

Example per node:

```text
rqlited:
  HTTP bind: 127.0.0.1:4001
  Raft bind: 127.0.0.1:4002
  Raft advertised address: 127.0.0.1:4101, 4102, or 4103

cloudflared tunnel:
  public HTTP hostname -> http://127.0.0.1:4001
  public TCP hostname  -> tcp://127.0.0.1:4002

cloudflared access tcp:
  rqlite-n1-raft.example.com -> 127.0.0.1:4101
  rqlite-n2-raft.example.com -> 127.0.0.1:4102
  rqlite-n3-raft.example.com -> 127.0.0.1:4103
```

The prepared `CLOUDFLARE_URL_1..3` values are enough for HTTP client tests, but they are not enough for rqlite Raft clustering unless they are paired with TCP Access applications and service credentials. Browser-based Cloudflare Access login is not suitable for an automated Raft peer.

This is why the runnable OSS lab defaults to a private Docker Raft network and documents the Cloudflare TCP overlay as the production-like no-direct-routing variant.

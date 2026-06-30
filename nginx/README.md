# Nginx reverse proxy (chat stack)

The tracked configuration is [`nginx.conf.template`](nginx.conf.template). **`nginx/nginx.conf` is generated** and must not be committed (see root `.gitignore`). The template no longer injects any secrets — chat is served by the FastAPI backend under JWT auth, so rendering is a plain copy.

## Render `nginx.conf`

```bash
./scripts/render_nginx_conf.sh
```

No environment variables are required (the template has no `${...}` substitutions; nginx `$variables` are preserved verbatim).

Docker example:

```bash
./scripts/render_nginx_conf.sh
docker run --rm -p 8080:8080 --add-host=host.docker.internal:host-gateway \
  -v "$(pwd)/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" nginx:alpine
```

## Routing overview

- `/api/v1/chat-messages`, `/api/v1/conversations`, `/api/v1/messages` → `yamato_backend` (langchain conversation workflow; **`proxy_buffering off`** so SSE tokens flush immediately).
- All other `/api/v1/*` paths → `yamato_backend`.
- `/` → `yamato_vite` (frontend dev/preview server).

There is **no Dify upstream** anymore. The previous Dify catch-all (which rewrote `/api/v1/*` → `/v1/*` on a separate Dify service) has been removed.

## Load balancing vs path routing

The default template defines **two upstream blocks**, each with **one** `server`. Nginx **does not** distribute load across multiple replicas until you add **multiple** `server` lines inside the same `upstream`.

Example: two FastAPI instances behind one upstream (round-robin by default):

```nginx
upstream yamato_backend {
    server 10.0.0.1:8000 max_fails=3 fail_timeout=30s;
    server 10.0.0.2:8000 max_fails=3 fail_timeout=30s;
    keepalive 64;
}
```

Notes for multi-instance setups:

- **WebSockets** (`/api/v1/document-tasks/ws/`; legacy `/api/v1/docs/ws/`): sticky routing may be required if the app assumes a fixed backend; consider `ip_hash` or `hash $cookie_... consistent;` on the upstream, or ensure the app is stateless with respect to which worker handles the socket.
- **Conversation SSE**: stateless per request, but the in-memory cancel registry is per-process — a `/chat-messages/{task_id}/stop` request must land on the same backend that is streaming. Use `ip_hash` or a session-affinity cookie if you scale to multiple backends.
- **Vite**: scale by adding more `server` entries to `yamato_vite`.

## Edge hardening (optional)

The template includes:

- **`limit_req`** on `/api/v1/chat-messages` (tune `rate` / `burst` in the template).
- **Commented `set_real_ip_from` / `real_ip_header`**: uncomment and set CIDRs when Nginx runs **behind** another trusted proxy so `X-Forwarded-For` and `$remote_addr` reflect the real client correctly.

TLS termination is not defined here; use your cloud load balancer, `certbot`, or another layer in front of this Nginx. If TLS terminates upstream, pass `X-Forwarded-Proto: https` and enable the real-IP block as appropriate.

## Smoke test

With Nginx listening on `8080` and backends reachable:

```bash
./scripts/nginx_smoke.sh
```

If `nginx/nginx.conf` is missing, the script runs `./scripts/render_nginx_conf.sh` unless `SKIP_NGINX_RENDER=1` is set. The smoke test probes `/api/v1/health` (override with `PROBE_PATH`).

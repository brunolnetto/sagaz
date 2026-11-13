# Visualization UI — CORS and authentication

This page answers the security questions for the `sagaz monitor` dashboard.
Installation, views, the HTTP API and analytics reports are covered in the
full setup guide: [docs/monitoring/visualization-ui.md](../monitoring/visualization-ui.md).

## Allowed origins

**Same origin only.** The monitor installs no CORS middleware, so browsers only
let pages served by the monitor itself read its API. Pages on other origins
cannot read the REST or SSE responses, and their cross-origin `POST /api/v1/events`
(which carries an `Authorization` header) fails the CORS preflight.

There is **no `SAGAZ_VIZ_ALLOWED_ORIGINS` setting**. If another web app must call
the API, put both behind the same reverse proxy so they share an origin, or
mount the app returned by `create_app()` inside your own FastAPI application and
add `CORSMiddleware` there with an explicit origin list.

## Authentication

| Surface | Default |
|---------|---------|
| Event ingestion (`POST /api/v1/events`) | Requires `Authorization: Bearer <token>` (constant-time comparison). Disabled with `503` unless a token is configured. `sagaz monitor` uses `SAGAZ_VISUALIZATION_TOKEN`, or generates a random 256-bit token per process and prints it for workers |
| Read endpoints (dashboard, REST, SSE, analytics) | **Unauthenticated** — intended for local use |
| Bind address | `127.0.0.1`; any other address requires `--unsafe-expose` and prints a warning |

## Recommended patterns

- **Local development** — the defaults: loopback bind, generated token, no auth on reads.
- **Remote access for a team** — keep the loopback bind and tunnel
  (`ssh -L 7070:127.0.0.1:7070 host`), or run behind a reverse proxy that
  authenticates users (OAuth2 proxy, mTLS, basic auth) and start the monitor
  with `--unsafe-expose`.
- **API-key style access for scripts** — enforce the key at the reverse proxy
  (e.g. require an `X-API-Key` header); the monitor itself does not check one
  on read endpoints.
- **Workers on other hosts** — set the same `SAGAZ_VISUALIZATION_TOKEN` on the
  monitor and every worker, and use HTTPS across untrusted networks.

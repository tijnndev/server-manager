# server-manager

A self-hosted web panel for managing Docker Compose stacks on a VPS. Create
stacks from templates or raw compose files, power them on and off, watch logs
live, edit files, pull from git, publish domains through the host nginx with
Let's Encrypt TLS and Cloudflare DNS, schedule cron jobs, and manage mail
accounts — all from a single browser UI.

Built in Go (backend) and React (frontend), deployed as a single Docker
container that talks to the host Docker daemon, host nginx, and a MariaDB
database.

## Features

- **Stacks** — create from built-in templates (Node.js, Go, Python, PHP,
  static, Vite, MariaDB, Minecraft, …) or from your own compose file / upload.
  Each stack lives in its own directory under `DATA_DIR` and is run with
  `docker compose -p <name>`.
- **Live status** — container status, CPU and memory per service, streamed
  logs, and a per-service shell, all pushed over a WebSocket.
- **Power actions** — start, stop, restart, rebuild (with `--no-cache` for
  frontend builds).
- **Files** — browse, edit (Monaco editor), upload and delete files inside a
  stack directory.
- **Git** — clone a repo into a stack, pull with automatic stash of local
  changes, ahead/behind and change overview. Works with SSH keys or a GitHub
  personal access token.
- **Domains** — publish a service on a hostname: writes an nginx site config
  on the host, validates with `nginx -t`, reloads nginx, issues a Let's
  Encrypt certificate with certbot, and optionally creates a proxied Cloudflare
  A record.
- **Schedules** — per-stack cron jobs (start / stop / restart).
- **Users & access** — admin and user roles, per-stack sub-user access,
  activity log.
- **Mail** — manage accounts on a [docker-mailserver](https://github.com/docker-mailserver/docker-mailserver)
  container, with Roundcube webmail included in the default compose setup.
- **Notifications** — optional Discord webhook for lifecycle events and
  crash alerts.

## Quick start

Requirements: a Linux host with Docker, nginx, certbot and git installed.

```bash
git clone https://github.com/tijnndev/server-manager.git
cd server-manager
cp .env.example .env
# edit .env: set ADMIN_PASSWORD, MYSQL_PASSWORD, MYSQL_ROOT_PASSWORD,
# and the mail hostname/domain for your own domain.

docker compose -f compose.yaml -f compose.nginx.yaml up -d --build
```

Open `http://<your-server>:7101` and log in with the `ADMIN_USER` /
`ADMIN_PASSWORD` from `.env`.

The `compose.nginx.yaml` overlay is required for domain publishing: it gives
the panel access to the host nginx config directories, the Let's Encrypt
certificates and the nginx pid file so it can validate and reload the host
nginx.

### What the default compose file runs

| Service     | Purpose                                              |
| ----------- | ---------------------------------------------------- |
| `db`        | MariaDB 11 for panel state                           |
| `panel`     | the server-manager panel (port 7101)                 |
| `mailserver`| docker-mailserver (SMTP/IMAP, ports 25/143/465/587/993) |
| `roundcube` | Roundcube webmail (port 8080)                        |

Mail is optional — if you don't want it, remove the `mailserver` and
`roundcube` services from `compose.yaml` (the panel's Mail page will simply
report that the container is not running).

## Configuration

All configuration is via environment variables (or a `.env` file next to the
compose file). See [docs/configuration.md](docs/configuration.md) for the full
reference.

## Development

```bash
# backend (Go 1.26+)
cd backend
go build ./...
go test ./...

# frontend (Node 22+)
cd frontend
npm ci
npm run dev        # vite dev server on :5174, proxies /api to :7101
npm run build      # typecheck + build to frontend/dist
```

Run the backend against a local database and it will serve the built frontend
from `frontend/dist` (set `FRONTEND_DIR` to override).

## Architecture

The backend is a single Go binary (`backend/cmd/server-manager`) with these
packages:

- `api` — HTTP routes, auth, WebSocket hub, file/git/domain/schedule handlers
- `runtime` — the supervisor: drives `docker compose` actions, watches Docker
  events, samples stats, streams logs
- `domain` — nginx site rendering/validation/reload, certbot, Cloudflare API
- `template` — YAML stack templates and compose rendering/parsing
- `store` / `db` — MariaDB persistence (schema in `db.go`)
- `auth` — bcrypt passwords, session tokens (SHA-256 hashed at rest)
- `schedule` — cron runner for stack schedules
- `mail` — docker-mailserver account management via `docker exec`
- `notify` — Discord webhook notifications
- `safe` — path-traversal-safe joins for the file API

See [docs/architecture.md](docs/architecture.md) for a deeper walkthrough.

## Documentation

- [Configuration reference](docs/configuration.md)
- [Stack templates](docs/templates.md)
- [HTTP API reference](docs/api.md)
- [Architecture](docs/architecture.md)
- [Mail setup](docs/mail.md)
- [Legacy migration](deploy/MIGRATION.md)

## Security notes

- The panel binds to `:7101` and is intended to be exposed to the internet.
  Set a strong `ADMIN_PASSWORD` and, in production, put it behind TLS (e.g. a
  reverse proxy) and set `COOKIE_SECURE=1`.
- The panel needs the Docker socket, host nginx config directories and
  certbot — it is a privileged component. Run it on a host you trust.
- See [SECURITY.md](SECURITY.md) for reporting vulnerabilities.

## License

[MIT](LICENSE)
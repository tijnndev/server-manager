# Architecture

server-manager is a single Go binary that runs inside a Docker container on
your VPS. It is a privileged component: it drives the host Docker daemon,
writes and reloads host nginx configs, runs certbot, and executes commands
inside containers.

```
                ┌─────────────────────────────────────────────┐
                │                panel container              │
  browser ────► │  ┌──────────┐   ┌───────────┐   ┌────────┐  │
  (7101)       │  │  api     │──►│ supervisor│──►│  hub   │  │
                │  │ (HTTP/WS)│   │ (runtime) │   │ (WS fan)│ │
                │  └──────────┘   └─────┬─────┘   └────────┘  │
                │        │              │                      │
                │  ┌─────▼─────┐   ┌────▼─────┐  ┌──────────┐ │
                │  │  store/db │   │  domain  │  │  mail    │ │
                │  │ (MariaDB) │   │(nginx/cf)│  │(dm exec) │ │
                │  └───────────┘   └──────────┘  └──────────┘ │
                └───────────┬───────────────┬─────────────────┘
                            │               │
                     ┌──────▼──────┐  ┌─────▼──────────────┐
                     │  MariaDB    │  │ host: docker, nginx,│
                     │  (db svc)   │  │ certbot, git, DATA_DIR│
                     └─────────────┘  └────────────────────┘
```

## Request flow

1. **`api`** (`backend/internal/api`) owns the HTTP mux, authentication and
   authorization. Every handler resolves the user from the session cookie and
   checks stack access (`ownerOr` / `CanAccess`). Mutating `/api/` requests
   require the `X-SM-Request: 1` header.
2. **`store` / `db`** persist everything in MariaDB. The schema is in
   `db.go` and applied idempotently on startup. Tables are prefixed `v2_`.
3. **`runtime`** (the supervisor) performs all Docker work. It shells out to
   `docker compose -p <name> --project-directory <dir>` for start/stop/
   restart/rebuild, and uses the Docker client library for events, stats,
   logs, exec and the interactive shell.
4. **`domain`** renders nginx site configs from the published domains, writes
   them to `NGINX_SITES_AVAILABLE`, symlinks into `NGINX_SITES_ENABLED`,
   validates with `nginx -t` (rolling back on failure) and reloads nginx
   (via `SIGHUP` to `NGINX_PID`, or `nginx -s reload`, or `systemctl reload`).
   TLS is issued with certbot; Cloudflare records are managed via the API.
5. **`hub`** fans WebSocket messages out to connected browsers.

## The supervisor

The supervisor (`runtime/supervisor.go`) is the heart of the system:

- **Actions** — `Apply` runs the compose steps for an action. `rebuild` runs
  `docker compose build` (adding `--no-cache` when the Dockerfile does a
  frontend build) then `up -d --force-recreate`. If a container name is held
  by an *unmanaged* container (e.g. a legacy-panel container), it is
  force-removed and the step retried once — this is the cutover path.
  Compose-managed conflicts are never touched.
- **Events** — a Docker events stream updates per-service status
  (`running` / `exited` / `missing`). A service that exits while its stack's
  desired state is `running` raises a crash (activity entry + Discord ping),
  rate-limited to once per minute.
- **Stats** — every 5 s, CPU and memory are sampled for running containers.
- **Logs** — when a browser subscribes to a stack, the supervisor tails the
  logs of each service (200-line replay on subscribe) and streams new lines
  through the hub. A 200-line tail is kept per service.
- **Resilience** — if the Docker connection drops, the supervisor reconnects
  and re-syncs state from `docker ps`.

## State model

- A **stack** is a directory under `DATA_DIR` containing a compose file (and
  any app files), plus a row in `v2_stacks`.
- **Services** are the compose services, stored in `v2_services` and kept in
  sync with the compose file (re-parsed after edits and power actions).
- **Desired state** (`running` / `stopped`) is persisted so the panel knows
  what a stack *should* be doing, which drives crash detection.
- **Domains**, **schedules**, **sub-users**, **activity**, **settings** and
  **template overrides** are each their own table.

## Security model

- Passwords are bcrypt-hashed; session tokens are random 256-bit values
  stored as SHA-256 hashes (the raw token only lives in the cookie).
- The file API joins user paths with `safe.Join`, which rejects absolute
  paths, `..` traversal and drive-letter/colon tricks.
- Git remotes are validated; SSH uses a dedicated `known_hosts` and
  `BatchMode=yes`; GitHub auth uses an `extraheader` so the token never lands
  in a URL.
- Uploads and file reads are size-capped (32 MiB upload, 1 MiB inline edit).
- The panel is intended to run on a host you trust; it cannot sandbox itself
  from the Docker socket or host nginx.
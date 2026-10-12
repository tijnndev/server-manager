# Configuration reference

All configuration is supplied as environment variables. The panel reads a
`.env` file from its working directory (or `../.env`) at startup; real
environment variables always win over `.env` values. When running via
`docker compose`, set them in your `.env` file — the compose file passes the
relevant ones into the `panel` service.

## Panel

| Variable         | Default              | Description                                              |
| ---------------- | -------------------- | -------------------------------------------------------- |
| `PANEL_ADDR`     | `:7101`              | Listen address for the HTTP server.                      |
| `PANEL_PORT`     | `7101`               | Host port published by the compose file (maps to 7101).  |
| `DATA_DIR`       | `data/stacks`        | Where stack directories (compose + files) are stored.    |
| `TEMPLATES_DIR`  | `templates`          | Directory with built-in template YAML files.             |
| `FRONTEND_DIR`   | `frontend/dist`      | Built frontend assets to serve.                          |
| `ADMIN_USER`     | `admin`              | Username seeded on first start.                          |
| `ADMIN_PASSWORD` | `admin`              | Password for the seeded admin. **Change this.**          |
| `COOKIE_SECURE`  | _(unset)_            | Set to `1` to mark the session cookie `Secure` (HTTPS).  |

## Database

The panel connects to MariaDB/MySQL. Three ways to configure, in priority
order:

1. `DB_HOST` (+ `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`) — used by the
   default compose file.
2. `DATABASE_DSN` — a full Go MySQL DSN, e.g.
   `user:pass@tcp(host:3306)/dbname?parseTime=true&charset=utf8mb4&multiStatements=true`.
3. `DATABASE_URI` — a `mysql://user:pass@host:3306/dbname` URL.

| Variable             | Default             | Description                    |
| -------------------- | ------------------- | ------------------------------ |
| `DB_HOST`            | _(unset)_           | Database host.                 |
| `DB_PORT`            | `3306`              | Database port.                 |
| `DB_USER`            | `server-manager`    | Database user.                 |
| `DB_PASSWORD`        | _(required)_        | Database password.             |
| `DB_NAME`            | `server-manager`    | Database name.                 |
| `MYSQL_DATABASE`     | `server-manager`    | Used by the `db` compose service. |
| `MYSQL_USER`         | `server-manager`    | Used by the `db` compose service. |
| `MYSQL_PASSWORD`     | `server-manager`    | Used by the `db` compose service. |
| `MYSQL_ROOT_PASSWORD`| `server-manager-root`| Root password for the `db` service. |

The schema is created automatically on startup (`CREATE TABLE IF NOT EXISTS`),
so no manual migration step is needed for a fresh install.

## nginx / domains

Used by the domain-publishing feature. The default values assume nginx is
installed on the host with the Debian/Ubuntu `sites-available` /
`sites-enabled` layout.

| Variable                 | Default                          | Description                              |
| ------------------------ | -------------------------------- | ---------------------------------------- |
| `NGINX_SITES_AVAILABLE`  | `/etc/nginx/sites-available`     | Where site configs are written.          |
| `NGINX_SITES_ENABLED`    | `/etc/nginx/sites-enabled`       | Where symlinks are created.              |
| `NGINX_PID`              | _(unset)_                        | Path to the host nginx pid file. When set, the panel sends `SIGHUP` to that pid to reload nginx (used with the `compose.nginx.yaml` overlay). |

The panel validates every config with `nginx -t` before reloading and rolls
back on failure.

## Mail

| Variable               | Default                 | Description                              |
| ---------------------- | ----------------------- | ---------------------------------------- |
| `MAIL_CONTAINER`       | `mailserver`            | Name of the docker-mailserver container. |
| `MAIL_HOSTNAME`        | `mail.tijnn.dev`        | Hostname for the mailserver (FQDN).      |
| `MAIL_DOMAIN`          | `tijnn.dev`             | Mail domain.                             |
| `POSTMASTER_ADDRESS`   | `postmaster@tijnn.dev`  | Postmaster account created at first start. |
| `POSTMASTER_PASSWORD`  | `changeme`              | Postmaster password. **Change this.**    |
| `ROUNDCUBE_PORT`       | `8080`                  | Host port for Roundcube webmail.         |

## Integrations (set in the UI, not env)

These are stored in the database and edited on the **Settings** page:

- **Discord webhook** — lifecycle and crash notifications.
- **Cloudflare token** — API token with DNS record permissions, used when
  publishing domains with the Cloudflare option.
- **Public IP** — the A record content for Cloudflare.
- **ACME email** — contact address for Let's Encrypt certificates.
- **GitHub token** — personal access token for pulling/cloning private repos.
  The `GITHUB_TOKEN` / `GH_TOKEN` environment variables are also honored as a
  fallback.

## Legacy migration

`deploy/migrate.sh` accepts `LEGACY_DIR` (default `/etc/server-manager`) and
passes through options to `migrate-legacy.py`. See
[deploy/MIGRATION.md](../deploy/MIGRATION.md) for details.
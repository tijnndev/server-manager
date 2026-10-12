# Legacy migratie (Python panel → Go panel)

One-shot migratie: users, settings, projecten (compose + bestanden), sub-users en domeinen
worden in één keer overgezet. De oude panel blijft gewoon draaien.

## Plug & play op de VPS

```bash
# 1. Remake-repo ophalen en .env invullen
cd /opt/server-manager        # checkout van de remake
cp .env.example .env          # ADMIN_PASSWORD, MYSQL_PASSWORD etc. instellen

# 2. Nieuwe panel starten (MariaDB + panel + mail) — overlay koppelt de host-nginx
docker compose -f compose.yaml -f compose.nginx.yaml up -d --build

# 3. Migratie draaien
sudo ./deploy/migrate.sh
```

Klaar. De script logt alles; bij een fout draait hij gewoon opnieuw (idempotent:
bestaande users/stacks/sub-users worden overgeslagen).

De `compose.nginx.yaml` overlay is verplicht voor domeinen: hij geeft de panel
`pid: host` + mounts voor `/etc/nginx/sites-*`, `/etc/letsencrypt` en de host
nginx pid-file, zodat de panel host-nginx-configs kan schrijven en herladen.

## Wat de migratie doet

- **Users** — aangeemaakt met nieuwe random wachtwoorden (legacy werkzeug-hashes
  zijn niet portabel). Wachtwoorden staan in `/var/backups/server-manager/migrated-passwords-*.txt` (chmod 600).
- **Settings** — eerste Discord webhook + Cloudflare API token uit `user_settings`.
- **Stacks** — elke `processes`-rij wordt een stack: compose-content ongewijzigd
  (hostpoorten `8000 + port_id` blijven staan), projectbestanden gekopieerd naar
  `DATA_DIR/<name>` (zonder het oude compose-bestand).
- **Sub-users** — legacy `sub_users` + de oorspronkelijke eigenaar krijgen toegang.
- **Domeinen** — opnieuw gepubliceerd via de nieuwe panel (TLS hergebruikt
  bestaande Let's Encrypt certificaten, certbot wordt overgeslagen als
  `/etc/letsencrypt/live/<host>/fullchain.pem` al bestaat).

Known caveat: legacy templates genereren Dockerfiles met `node:18`. Nieuwere
build-tooling (rolldown/vite) vereist Node >= 20.12 — pas de Dockerfile van
zo'n stack aan naar `node:22` (Files-tab) of reset/edit het `build-vite`
template (Templates-pagina). De migrator verwijdert automatisch de legacy
`build-vite` helper-service uit compose-bestanden (die probeerde `npm` te
starten in de httpd-image en crashte bij het starten van de stack).

Migrated stacks worden **niet gestart**: de legacy containers blijven op hun
poorten draaien en de oude nginx-configs blijven werken.

## Side-by-side draaien

- Legacy panel: `systemctl status server-manager` (Flask + zijn containers).
- Nieuwe panel: `docker compose ps` (poort 7101, geen conflict met legacy poorten).
- Legacy poorten: `8001, 8002, ...` — nieuwe panel gebruikt dezelfde poorten pas
  bij cutover, dus er is geen conflict.

## Cutover (later)

1. In de nieuwe panel: stacks starten (zelfde hostpoorten → urls blijven werken).
   - Start de stack een containernaam-conflict met een legacy container, dan
     vervangt de panel die automatisch (force-remove + retry). Compose-managed
     containers van andere stacks worden nooit automatisch verwijderd.
2. Check dat elke site reageert.
3. Legacy nginx-siteconfigs voor gemigreerde domeinen verwijderen
   (`/etc/nginx/sites-enabled/<domein>`) — de nieuwe panel heeft eigen configs
   met dezelfde servernamen geschreven.
4. Legacy panel stoppen: `systemctl disable --now server-manager`.

## Opties

```
--legacy-dir /etc/server-manager   legacy installatie (met .env + active-servers/)
--panel http://127.0.0.1:7101      nieuwe panel
--data-dir /var/lib/server-manager/stacks
--db-uri ...                       override legacy DATABASE_URI
--admin/--password                 override panel-credentials (default: .env)
--no-files                         projectbestanden overslaan
--no-domains                       domein-migratie overslaan
--dry-run                          alleen tonen wat er gaat gebeuren
```

Vereisten: Python 3 (pymysql uit de legacy venv, of de `mysql` CLI als fallback).
De wrapper `deploy/migrate.sh` kiest automatisch de legacy venv-python.
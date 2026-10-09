#!/usr/bin/env python3
"""One-shot migration from the legacy (Python) server-manager to the Go panel.

Reads the legacy MySQL database and active-servers directory, then:
  1. creates migrated users in the new panel (fresh random passwords)
  2. migrates Discord/Cloudflare settings
  3. imports every legacy project as a stack (compose preserved, host ports preserved)
  4. copies the project files into the new stacks directory
  5. grants legacy sub-users access to their stacks
  6. re-publishes legacy domains through the new panel

Design notes:
- Migrated stacks are created in the "stopped" desired state. The legacy
  containers keep serving traffic on their existing host ports (8000+port_id),
  so the legacy nginx configs keep working while both panels run side by side.
- At cutover, start the migrated stacks in the new panel; they bind the same
  host ports, so URLs do not change. Remove the legacy nginx site configs for
  migrated domains once the new stacks serve traffic.
- Legacy password hashes (werkzeug) cannot be verified by the Go panel, so
  users get fresh random passwords written to a root-only file.

Usage:
  python3 migrate-legacy.py [--legacy-dir /etc/server-manager] \
      [--panel http://127.0.0.1:7101] [--data-dir /var/lib/server-manager/stacks] \
      [--admin admin --password ...] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import stat
import string
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

COMPOSE_NAMES = ["compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"]
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def log(msg: str) -> None:
    print(msg, flush=True)


def warn(msg: str) -> None:
    print(f"  ! {msg}", flush=True)


# ---------------------------------------------------------------------------
# Legacy MySQL access (pymysql when available, `mysql` CLI as fallback)
# ---------------------------------------------------------------------------

class LegacyDB:
    def __init__(self, uri: str):
        self.uri = uri
        self.pymysql = None
        self.cli = None
        try:
            import pymysql  # type: ignore

            self.pymysql = pymysql
            return
        except ImportError:
            pass
        if shutil.which("mysql"):
            self.cli = "mysql"
            return
        raise SystemExit("Need either the pymysql module or the `mysql` CLI to read the legacy database.")

    def _conn_params(self) -> dict:
        info = urllib.parse.urlparse(self.uri)
        return {
            "host": info.hostname or "localhost",
            "port": info.port or 3306,
            "user": urllib.parse.unquote(info.username or "root"),
            "password": urllib.parse.unquote(info.password or ""),
            "database": (info.path or "/server-manager").lstrip("/") or "server-manager",
        }

    def query(self, sql: str) -> list[dict]:
        if self.pymysql is not None:
            import pymysql  # type: ignore

            p = self._conn_params()
            conn = pymysql.connect(
                host=p["host"], port=p["port"], user=p["user"], password=p["password"], database=p["database"],
                unix_socket=p["host"] in ("localhost",) and "/var/run/mysqld/mysqld.sock" or None,
                cursorclass=pymysql.cursors.DictCursor,
            )
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    return list(cur.fetchall())
            finally:
                conn.close()
        # mysql CLI fallback: batch TSV with header
        p = self._conn_params()
        cmd = ["mysql", "--batch", "--skip-column-names", "-h", p["host"], "-P", str(p["port"]),
               "-u", p["user"], p["database"], "-e", sql]
        if p["password"]:
            cmd[1:1] = [f"--password={p['password']}"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"mysql CLI failed: {res.stderr.strip()}")
        cols = [c.strip() for c in sql.split("SELECT", 1)[1].split("FROM", 1)[0].split(",")]
        rows = []
        for line in res.stdout.splitlines():
            vals = line.split("\t")
            row = {}
            for i, col in enumerate(cols):
                row[col.strip().split()[-1] if " " in col.strip() else col.strip()] = vals[i] if i < len(vals) else None
            rows.append(row)
        return rows


def read_legacy_env(legacy_dir: Path) -> str:
    env_path = legacy_dir / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            m = re.match(r"^DATABASE_URI=(.*)$", line.strip())
            if m and m.group(1).strip():
                return m.group(1).strip()
    return "mysql+pymysql://root@localhost:3306/server-manager"


# ---------------------------------------------------------------------------
# New panel API client
# ---------------------------------------------------------------------------

class Panel:
    def __init__(self, base: str, username: str, password: str):
        self.base = base.rstrip("/")
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def _req(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("X-SM-Request", "1")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(req, timeout=60) as res:
                return res.status, json.loads(res.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read().decode() or "{}")
            except Exception:
                payload = {}
            return e.code, payload

    def login(self, username: str, password: str) -> None:
        code, data = self._req("POST", "/api/auth/login", {"username": username, "password": password})
        if code != 200:
            raise SystemExit(f"Panel login failed ({code}): {data.get('error', data)}")

    def users(self) -> list[dict]:
        code, data = self._req("GET", "/api/users")
        return data if code in (200, 201) else []

    def create_user(self, username: str, password: str, role: str) -> tuple[bool, str]:
        code, data = self._req("POST", "/api/users", {"username": username, "password": password, "role": role})
        if code in (200, 201):
            return True, "created"
        return False, str(data.get("error", code))

    def save_settings(self, settings: dict) -> tuple[bool, str]:
        code, data = self._req("PUT", "/api/settings", settings)
        return code in (200, 201), str(data.get("error", code))

    def create_stack(self, name: str, description: str, compose: str) -> tuple[bool, str]:
        code, data = self._req("POST", "/api/stacks", {"name": name, "description": description, "compose": compose})
        if code in (200, 201):
            return True, "created"
        if code == 409:
            return True, "already exists"
        return False, str(data.get("error", code))

    def stack(self, name: str) -> dict | None:
        code, data = self._req("GET", f"/api/stacks/{name}")
        return data.get("stack") if code in (200, 201) else None

    def publish(self, name: str, hostname: str, service: str, tls: bool) -> tuple[bool, list[str]]:
        code, data = self._req("POST", f"/api/stacks/{name}/publish",
                               {"hostname": hostname, "service": service, "tls": tls, "cloudflare": False})
        if code in (200, 201):
            return True, data.get("warnings", [])
        return False, [str(data.get("error", code))]

    def add_subuser(self, name: str, username: str) -> tuple[bool, str]:
        code, data = self._req("POST", f"/api/stacks/{name}/subusers", {"username": username})
        if code in (200, 201):
            return True, "added"
        return False, str(data.get("error", code))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return re.sub(r"-{2,}", "-", s) or "stack"


def first_published_service(compose: str) -> str | None:
    """Best-effort parse: first service with a host port mapping in a compose file."""
    svc = None
    for line in compose.splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        m = re.match(r"^([A-Za-z0-9_.-]+):\s*$", stripped)
        if indent <= 2 and m:
            svc = m.group(1)
            continue
        if svc and re.match(r"^[-\"]?\s*(?:\")?\d+:\d+", stripped):
            return svc
    return None


def find_compose(project_dir: Path) -> Path | None:
    for n in COMPOSE_NAMES:
        p = project_dir / n
        if p.is_file():
            return p
    return None


def copy_tree(src: Path, dst: Path) -> None:
    def ignore(_dir: str, names: list[str]) -> set[str]:
        return {n for n in names if n.lower() in COMPOSE_NAMES}

    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=ignore, symlinks=True)


def gen_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(16))


def write_passwords(path: Path, entries: list[tuple[str, str]]) -> None:
    lines = [f"{user}: {pw}" for user, pw in entries]
    path.write_text("\n".join(lines) + "\n")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Migrate legacy Python server-manager to the Go panel")
    ap.add_argument("--legacy-dir", default="/etc/server-manager", help="Legacy install dir (contains .env and active-servers/)")
    ap.add_argument("--panel", default="http://127.0.0.1:7101", help="New panel base URL")
    ap.add_argument("--data-dir", default="/var/lib/server-manager/stacks", help="New panel stacks directory")
    ap.add_argument("--admin", default=None, help="New panel admin username (default: ADMIN_USER from panel .env)")
    ap.add_argument("--password", default=None, help="New panel admin password (default: ADMIN_PASSWORD from panel .env)")
    ap.add_argument("--db-uri", default=None, help="Override legacy DATABASE_URI")
    ap.add_argument("--no-files", action="store_true", help="Skip copying project files")
    ap.add_argument("--no-domains", action="store_true", help="Skip domain migration")
    ap.add_argument("--dry-run", action="store_true", help="Show what would happen without changing anything")
    args = ap.parse_args()

    legacy_dir = Path(args.legacy_dir)
    servers_dir = legacy_dir / "active-servers"

    # Panel credentials: args > local .env next to this script > defaults
    env_path = Path(__file__).resolve().parent.parent / ".env"
    panel_env: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                panel_env[k.strip()] = v.strip()
    admin = args.admin or panel_env.get("ADMIN_USER", "admin")
    password = args.password or panel_env.get("ADMIN_PASSWORD", "admin")
    data_dir = Path(args.data_dir)

    db_uri = args.db_uri or read_legacy_env(legacy_dir)
    log(f"Legacy DB   : {db_uri.split('@')[-1]}")
    log(f"Legacy dir  : {legacy_dir}")
    log(f"Panel       : {args.panel}")
    log(f"Stacks dir  : {data_dir}")
    log("")

    db = LegacyDB(db_uri)
    panel = Panel(args.panel, admin, password)
    panel.login(admin, password)

    existing_users = {u["username"]: u for u in panel.users()}

    # --- users -------------------------------------------------------------
    log("== Users ==")
    new_passwords: list[tuple[str, str]] = []
    user_by_email: dict[str, str] = {}
    legacy_users = db.query("SELECT id, username, email, role FROM users")
    for u in legacy_users:
        username, email = str(u["username"]), str(u["email"])
        role = "admin" if str(u["role"]).lower() == "admin" else "user"
        user_by_email[email] = username
        if username in existing_users or username == admin:
            log(f"  = {username}: already exists, skipped")
            continue
        if args.dry_run:
            log(f"  + {username}: would create ({role}) with a fresh random password")
            continue
        pw = gen_password()
        ok, msg = panel.create_user(username, pw, role)
        log(f"  + {username}: {msg} ({role})")
        if ok:
            new_passwords.append((username, pw))
    if new_passwords:
        pw_file = Path("/var/backups/server-manager") / f"migrated-passwords-{time.strftime('%Y%m%d-%H%M%S')}.txt"
        pw_file.parent.mkdir(parents=True, exist_ok=True)
        write_passwords(pw_file, new_passwords)
        log(f"  i fresh passwords written to {pw_file} (chmod 600)")
    log("")

    # --- settings ----------------------------------------------------------
    log("== Settings ==")
    try:
        rows = db.query("SELECT discord_webhook_url, cloudflare_api_token FROM user_settings")
        discord = next((str(r["discord_webhook_url"]) for r in rows if r["discord_webhook_url"]), "")
        cf_token = next((str(r["cloudflare_api_token"]) for r in rows if r["cloudflare_api_token"]), "")
        if discord or cf_token:
            if args.dry_run:
                log("  + would migrate Discord webhook / Cloudflare token")
            else:
                ok, msg = panel.save_settings({"discordWebhook": discord, "cloudflareToken": cf_token, "publicIP": "", "acmeEmail": ""})
                log(f"  + settings saved: {msg}" if ok else f"  ! settings failed: {msg}")
        else:
            log("  = no Discord/Cloudflare settings found")
    except Exception as e:  # table may not exist
        warn(f"settings skipped: {e}")
    log("")

    # --- processes -> stacks -------------------------------------------------
    log("== Projects ==")
    processes = db.query(
        "SELECT name, command, type, file_location, description, domain, port_id, owner_id FROM processes"
    )
    email_by_id = {str(u["id"]): str(u["email"]) for u in legacy_users}
    summary = {"created": 0, "exists": 0, "failed": 0, "domains": 0}

    for p in processes:
        raw_name = str(p["name"])
        name = raw_name if NAME_RE.match(raw_name.lower()) else slugify(raw_name)
        desc = str(p["description"] or "").strip()
        log(f"- {raw_name}" + (f" -> {name}" if name != raw_name else ""))

        project_dir = Path(str(p["file_location"] or "")) if p["file_location"] else servers_dir / raw_name
        if not project_dir.is_dir():
            project_dir = servers_dir / raw_name
        compose_path = find_compose(project_dir) if project_dir.is_dir() else None
        if compose_path is None:
            warn(f"no compose file in {project_dir} — import manually")
            summary["failed"] += 1
            continue
        compose = compose_path.read_text()

        # 1. stack record (creates <data-dir>/<name>/compose.yaml)
        if args.dry_run:
            log(f"  + would create stack '{name}' from {compose_path.name} (desired: stopped)")
        else:
            ok, msg = panel.create_stack(name, desc, compose)
            if not ok:
                warn(f"stack creation failed: {msg}")
                summary["failed"] += 1
                continue
            log(f"  + stack: {msg}")
            summary["created" if msg == "created" else "exists"] += 1

        # 2. project files
        target = data_dir / name
        if args.no_files:
            log("  = file copy skipped (--no-files)")
        elif not project_dir.is_dir():
            warn(f"project dir missing: {project_dir}")
        else:
            if args.dry_run:
                log(f"  + would copy {project_dir} -> {target}")
            else:
                try:
                    copy_tree(project_dir, target)
                    log(f"  + files copied to {target}")
                except Exception as e:
                    warn(f"file copy failed: {e}")

        # 3. grant the legacy owner access
        owner_email = email_by_id.get(str(p["owner_id"]))
        owner_username = user_by_email.get(owner_email or "", "")
        if owner_username and owner_username != admin:
            if args.dry_run:
                log(f"  + would grant access to {owner_username}")
            else:
                ok, msg = panel.add_subuser(name, owner_username)
                log(f"  + access for {owner_username}: {msg}" if ok else f"  ! access for {owner_username}: {msg}")

        # 4. sub-users from the legacy panel
        try:
            subs = db.query(f"SELECT email FROM sub_users WHERE process = '{raw_name.replace(chr(39), '')}'")
        except Exception:
            subs = []
        for s in subs:
            sub_username = user_by_email.get(str(s["email"]))
            if not sub_username:
                continue
            if args.dry_run:
                log(f"  + would grant access to sub-user {sub_username}")
                continue
            ok, msg = panel.add_subuser(name, sub_username)
            log(f"  + sub-user {sub_username}: {msg}" if ok else f"  ! sub-user {sub_username}: {msg}")

        # 5. domain
        domain = str(p["domain"] or "").strip()
        if domain and domain != raw_name and not args.no_domains:
            if args.dry_run:
                svc = first_published_service(compose)
            else:
                st = panel.stack(name)
                svc = None
                for s in st.get("services", []):
                    if s.get("hostPort"):
                        svc = s["name"]
                        break
            if not svc:
                warn(f"domain {domain}: no published service found in compose")
            elif args.dry_run:
                log(f"  + would publish {domain} -> {svc} (TLS reuses the existing certificate if present)")
            else:
                ok, warnings = panel.publish(name, domain, svc, tls=True)
                if ok:
                    log(f"  + domain {domain} -> {svc}")
                    summary["domains"] += 1
                    for w in warnings:
                        warn(w)
                else:
                    for w in warnings:
                        warn(w)

    log("")
    log(f"Done. stacks created: {summary['created']}, already present: {summary['exists']}, "
        f"domains: {summary['domains']}, failed: {summary['failed']}")
    log("")
    log("Side-by-side notes:")
    log("- Migrated stacks are STOPPED; the legacy containers keep serving their host ports.")
    log("- Legacy nginx configs keep working unchanged during side-by-side operation.")
    log("- Cutover: start the stacks in the new panel (same ports), then remove the legacy")
    log("  nginx site configs for migrated domains once traffic flows through the new panel.")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
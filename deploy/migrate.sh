#!/usr/bin/env bash
# Wrapper for migrate-legacy.py: prefers the legacy venv python (has pymysql),
# falls back to python3 + mysql CLI. Run as root on the VPS.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LEGACY_DIR="${LEGACY_DIR:-/etc/server-manager}"

PY=""
for candidate in "$LEGACY_DIR/venv/bin/python3" "$LEGACY_DIR/venv/bin/python" python3; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then echo "No python3 found" >&2; exit 1; fi
echo "Using python: $PY"

exec "$PY" "$SCRIPT_DIR/migrate-legacy.py" --legacy-dir "$LEGACY_DIR" "$@"
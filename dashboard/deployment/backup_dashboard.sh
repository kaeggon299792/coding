#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/kaekun/coding-dashboard/dashboard}"
BACKUP_ROOT="${BACKUP_ROOT:-/home/kaekun/backups/management-dashboard}"
ENV_FILE="${ENV_FILE:-${APP_DIR}/.env}"
STAMP="$(date +%Y%m%d-%H%M%S)"
TARGET="${BACKUP_ROOT}/${STAMP}"

mkdir -p "${TARGET}"
cd "${APP_DIR}"

set -a
source "${ENV_FILE}"
set +a

DB_PATH="${DASHBOARD_DB_FILE:-${APP_DIR}/dashboard.db}"
if [[ "${DB_PATH}" != /* ]]; then DB_PATH="${APP_DIR}/${DB_PATH}"; fi
test -f "${DB_PATH}"

python - "${DB_PATH}" "${TARGET}/dashboard.db" <<'PY'
import sqlite3
import sys
source, target = sys.argv[1:3]
with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
    result = dst.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise SystemExit(f"backup integrity check failed: {result}")
PY

git rev-parse HEAD > "${TARGET}/git-commit.txt"
sha256sum "${TARGET}/dashboard.db" > "${TARGET}/SHA256SUMS"
printf '%s\n' "${TARGET}"


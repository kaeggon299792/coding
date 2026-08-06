#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/kaekun/coding-dashboard/dashboard}"
ENV_FILE="${ENV_FILE:-${APP_DIR}/.env}"
BACKUP_PATH="${1:?backup_dashboard.sh가 만든 백업 디렉터리를 입력하세요}"
BACKUP_DB="${BACKUP_PATH}/dashboard.db"
BACKUP_SOURCE="${BACKUP_PATH}/source-before.tar.gz"
BACKUP_COMMIT_FILE="${BACKUP_PATH}/git-commit.txt"

cd "${APP_DIR}"
test -f "${BACKUP_DB}"
test -f "${BACKUP_SOURCE}"
test -f "${BACKUP_COMMIT_FILE}"

set -a
source "${ENV_FILE}"
set +a
DB_PATH="${DASHBOARD_DB_FILE:-${APP_DIR}/dashboard.db}"
if [[ "${DB_PATH}" != /* ]]; then DB_PATH="${APP_DIR}/${DB_PATH}"; fi

python - "${BACKUP_DB}" "${DB_PATH}" <<'PY'
import os
import sqlite3
import sys
source, target = sys.argv[1:3]
temporary = target + ".restore.tmp"
if os.path.exists(temporary):
    os.remove(temporary)
with sqlite3.connect(source) as src, sqlite3.connect(temporary) as dst:
    src.backup(dst)
    assert dst.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
os.replace(temporary, target)
PY

REPO_DIR="$(git rev-parse --show-toplevel)"
BACKUP_COMMIT="$(cat "${BACKUP_COMMIT_FILE}")"
python "${APP_DIR}/deployment/sync_tracked_source.py" \
  --repo "${REPO_DIR}" --previous origin/main --target "${BACKUP_COMMIT}"
tar -xzf "${BACKUP_SOURCE}" -C "$(dirname "${APP_DIR}")"
chmod 600 "${DB_PATH}"
printf '%s\n' "롤백 완료. PythonAnywhere Web 탭에서 Reload 하세요."

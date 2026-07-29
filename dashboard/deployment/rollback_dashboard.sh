#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/kaekun/coding-dashboard/dashboard}"
ENV_FILE="${ENV_FILE:-${APP_DIR}/.env}"
COMMIT="${1:?복원할 git commit을 입력하세요}"
BACKUP_DB="${2:?복원할 dashboard.db 백업 경로를 입력하세요}"

cd "${APP_DIR}"
test -f "${BACKUP_DB}"
test -z "$(git status --porcelain)" || {
  echo "중단: 운영 작업 폴더에 커밋되지 않은 변경이 있습니다." >&2
  exit 1
}

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

git checkout --detach "${COMMIT}"
printf '%s\n' "롤백 완료. PythonAnywhere Web 탭에서 Reload 하세요."


#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/kaekun/coding-dashboard/dashboard}"
PYTHON="${PYTHON:-python3}"
TARGET_REF="${1:-origin/feature/dashboard-tips-integration}"

cd "${APP_DIR}"
test -z "$(git status --porcelain)" || {
  echo "중단: 운영 작업 폴더에 커밋되지 않은 변경이 있습니다." >&2
  exit 1
}

BACKUP_PATH="$("${APP_DIR}/deployment/backup_dashboard.sh")"
PREVIOUS_COMMIT="$(git rev-parse HEAD)"
printf 'backup=%s\nprevious_commit=%s\n' "${BACKUP_PATH}" "${PREVIOUS_COMMIT}"

git fetch --prune origin
git checkout --detach "${TARGET_REF}"
"${PYTHON}" -m pip install -r requirements.txt
"${PYTHON}" -m pytest -q tests
"${PYTHON}" - <<'PY'
from extensions import dashboard_db
connection = dashboard_db()
assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
connection.close()
PY

printf '%s\n' \
  "검증 완료. PythonAnywhere Web 탭에서 Reload 후 아래를 확인하세요." \
  "  /" \
  "  /login" \
  "  /performance/economy" \
  "  /performance/holidays?year=2026" \
  "롤백: deployment/rollback_dashboard.sh '${PREVIOUS_COMMIT}' '${BACKUP_PATH}/dashboard.db'"


#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/kaekun/coding-dashboard/dashboard}"
PYTHON="${PYTHON:-python3}"
TARGET_REF="${1:-origin/feature/dashboard-tips-integration}"

cd "${APP_DIR}"

BACKUP_PATH="$("${APP_DIR}/deployment/backup_dashboard.sh")"
PREVIOUS_COMMIT="$(git rev-parse HEAD)"
printf 'backup=%s\nprevious_commit=%s\n' "${BACKUP_PATH}" "${PREVIOUS_COMMIT}"

REPO_DIR="$(git rev-parse --show-toplevel)"
git -C "${REPO_DIR}" fetch --prune origin
# PythonAnywhere 운영 폴더에는 DB·업로드·과거 백업 등 Git 비관리 파일이
# 존재하므로 checkout 대신 검증된 ref의 dashboard 트리만 안전하게 겹쳐 씁니다.
git -C "${REPO_DIR}" archive "${TARGET_REF}" dashboard |
  tar -x -C "${REPO_DIR}"
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
  "롤백: deployment/rollback_dashboard.sh '${BACKUP_PATH}'"

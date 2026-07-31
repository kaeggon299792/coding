#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/kaekun/coding-dashboard/dashboard}"
PYTHON="${PYTHON:-/home/kaekun/.virtualenvs/mgmt-dashboard/bin/python}"
TARGET_REF="${1:-origin/feature/dashboard-tips-integration}"

cd "${APP_DIR}"
BACKUP_PATH="$("${APP_DIR}/deployment/backup_dashboard.sh")"
PREVIOUS_COMMIT="$(git rev-parse HEAD)"
printf 'backup=%s\nprevious_commit=%s\n' "${BACKUP_PATH}" "${PREVIOUS_COMMIT}"

REPO_DIR="$(git rev-parse --show-toplevel)"
git -C "${REPO_DIR}" fetch --prune origin
git -C "${REPO_DIR}" archive "${TARGET_REF}" dashboard | tar -x -C "${REPO_DIR}"

"${PYTHON}" -m pip install -q -r requirements.txt
"${PYTHON}" -m compileall -q .
"${PYTHON}" -m pytest -q \
  tests/test_auth.py \
  tests/test_schema_migration.py \
  tests/test_seo.py \
  tests/test_source_data_repository.py
"${PYTHON}" - <<'PY'
from extensions import dashboard_db

connection = dashboard_db()
assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
connection.close()
PY

touch "${APP_DIR}/app.py" /var/www/casino_shingoon_me_wsgi.py /var/www/dashboard_shingoon_me_wsgi.py
nohup "${APP_DIR}/deployment/post_deploy_verify.sh" "${BACKUP_PATH}" >/dev/null 2>&1 &

printf '%s\n' \
  "Fast deployment and reload complete." \
  "Full tests are running in the background." \
  "Status: ${APP_DIR}/logs/post-deploy-latest.status" \
  "On failure, the deployment is automatically rolled back and reloaded." \
  "Manual rollback: deployment/rollback_dashboard.sh '${BACKUP_PATH}'"

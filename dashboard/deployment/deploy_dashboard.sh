#!/usr/bin/env bash
set -euo pipefail
umask 077

APP_DIR="${APP_DIR:-/home/kaekun/coding-dashboard/dashboard}"
PYTHON="${PYTHON:-/home/kaekun/.virtualenvs/mgmt-dashboard/bin/python}"
TARGET_REF="${1:-origin/main}"
VERIFY_MODE="${DEPLOY_VERIFY_MODE:-smoke}"
ENV_FILE="${ENV_FILE:-${APP_DIR}/.env}"

cd "${APP_DIR}"

secure_runtime_permissions() {
  chmod 600 "${ENV_FILE}" 2>/dev/null || true
  if [[ -f "${APP_DIR}/dashboard.db" ]]; then
    chmod 600 "${APP_DIR}/dashboard.db"
  fi
  if [[ -d "${APP_DIR}/logs" ]]; then
    chmod 700 "${APP_DIR}/logs"
    find "${APP_DIR}/logs" -type f -exec chmod 600 {} +
  fi
}

secure_runtime_permissions
BACKUP_PATH="$("${APP_DIR}/deployment/backup_dashboard.sh")"
PREVIOUS_COMMIT="$(git rev-parse origin/main)"
printf 'backup=%s\nprevious_commit=%s\n' "${BACKUP_PATH}" "${PREVIOUS_COMMIT}"

REPO_DIR="$(git rev-parse --show-toplevel)"
git -C "${REPO_DIR}" fetch --prune origin
"${PYTHON}" "${APP_DIR}/deployment/sync_tracked_source.py" \
  --repo "${REPO_DIR}" --previous "${PREVIOUS_COMMIT}" --target "${TARGET_REF}"
git -C "${REPO_DIR}" archive "${TARGET_REF}" dashboard | tar -x -C "${REPO_DIR}"

"${PYTHON}" -m pip install -q -r requirements.txt
"${PYTHON}" -m compileall -q .
"${PYTHON}" - <<'PY'
from pathlib import Path

from app import app
from config import DASHBOARD_DB_FILE
from extensions import dashboard_db
from scripts.import_paradise_vip_visits import import_paradise_vip_visits
from scripts.import_company_financials import import_financials

import_paradise_vip_visits(
    DASHBOARD_DB_FILE,
    Path("data/paradise_vip_visits_20260806.json"),
)
import_financials(
    DASHBOARD_DB_FILE,
    Path("data/company_financials_consolidated_20260806.json"),
)

required_endpoints = {
    "public_home",
    "auth.login",
    "auth.google_login",
    "auth.google_callback",
    "auth.my_account",
    "auth.withdraw_account",
    "market_trend_page",
}
registered = {rule.endpoint for rule in app.url_map.iter_rules()}
assert required_endpoints <= registered
connection = dashboard_db()
assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
connection.close()
PY

secure_runtime_permissions

touch "${APP_DIR}/app.py" /var/www/casino_shingoon_me_wsgi.py /var/www/www_casinoin_kr_wsgi.py
VERIFY_TARGETS=()
if [[ -n "${DEPLOY_TEST_TARGETS:-}" ]]; then
  read -r -a VERIFY_TARGETS <<< "${DEPLOY_TEST_TARGETS}"
fi
nohup "${APP_DIR}/deployment/post_deploy_verify.sh" \
  "${BACKUP_PATH}" "${VERIFY_MODE}" "${VERIFY_TARGETS[@]}" >/dev/null 2>&1 &

printf '%s\n' \
  "Fast deployment and reload complete after startup and integrity checks." \
  "Risk-based ${VERIFY_MODE} verification is running in the background." \
  "Status: ${APP_DIR}/logs/post-deploy-latest.status" \
  "On failure, the deployment is automatically rolled back and reloaded." \
  "Manual rollback: deployment/rollback_dashboard.sh '${BACKUP_PATH}'"

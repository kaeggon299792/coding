#!/usr/bin/env bash
set -uo pipefail

APP_DIR="${APP_DIR:-/home/kaekun/coding-dashboard/dashboard}"
PYTHON="${PYTHON:-/home/kaekun/.virtualenvs/mgmt-dashboard/bin/python}"
BACKUP_PATH="${1:?backup path is required}"
LOG_DIR="${APP_DIR}/logs"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="${LOG_DIR}/post-deploy-${STAMP}.log"
STATUS_FILE="${LOG_DIR}/post-deploy-latest.status"

mkdir -p "${LOG_DIR}"
cd "${APP_DIR}"
printf 'RUNNING %s log=%s backup=%s\n' "$(date --iso-8601=seconds)" "${LOG_FILE}" "${BACKUP_PATH}" > "${STATUS_FILE}"

if "${PYTHON}" -m pytest -q tests > "${LOG_FILE}" 2>&1; then
  printf 'PASSED %s log=%s backup=%s\n' "$(date --iso-8601=seconds)" "${LOG_FILE}" "${BACKUP_PATH}" > "${STATUS_FILE}"
  exit 0
fi

printf '\nFull post-deploy tests failed. Starting automatic rollback.\n' >> "${LOG_FILE}"
if "${APP_DIR}/deployment/rollback_dashboard.sh" "${BACKUP_PATH}" >> "${LOG_FILE}" 2>&1; then
  touch "${APP_DIR}/app.py" /var/www/casino_shingoon_me_wsgi.py /var/www/dashboard_shingoon_me_wsgi.py
  printf 'ROLLED_BACK %s log=%s backup=%s\n' "$(date --iso-8601=seconds)" "${LOG_FILE}" "${BACKUP_PATH}" > "${STATUS_FILE}"
else
  printf 'ROLLBACK_FAILED %s log=%s backup=%s\n' "$(date --iso-8601=seconds)" "${LOG_FILE}" "${BACKUP_PATH}" > "${STATUS_FILE}"
fi
exit 1

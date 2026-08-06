#!/usr/bin/env bash
set -uo pipefail

APP_DIR="${APP_DIR:-/home/kaekun/coding-dashboard/dashboard}"
PYTHON="${PYTHON:-/home/kaekun/.virtualenvs/mgmt-dashboard/bin/python}"
BACKUP_PATH="${1:?backup path is required}"
VERIFY_MODE="${2:-smoke}"
shift 2 || true
LOG_DIR="${APP_DIR}/logs"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="${LOG_DIR}/post-deploy-${STAMP}.log"
STATUS_FILE="${LOG_DIR}/post-deploy-latest.status"

mkdir -p "${LOG_DIR}"
cd "${APP_DIR}"
printf 'RUNNING %s mode=%s log=%s backup=%s\n' "$(date --iso-8601=seconds)" "${VERIFY_MODE}" "${LOG_FILE}" "${BACKUP_PATH}" > "${STATUS_FILE}"

case "${VERIFY_MODE}" in
  full)
    TEST_TARGETS=(tests)
    ;;
  custom)
    TEST_TARGETS=("$@")
    if [[ ${#TEST_TARGETS[@]} -eq 0 ]]; then
      printf 'custom verification requires DEPLOY_TEST_TARGETS\n' > "${LOG_FILE}"
      TEST_TARGETS=(tests/test_auth.py tests/test_navigation_ia.py)
    fi
    ;;
  smoke)
    TEST_TARGETS=(tests/test_auth.py tests/test_navigation_ia.py)
    ;;
  skip)
    printf 'SKIPPED %s mode=skip log=%s backup=%s\n' "$(date --iso-8601=seconds)" "${LOG_FILE}" "${BACKUP_PATH}" > "${STATUS_FILE}"
    printf 'Automated pytest skipped; deployment requires manual URL verification.\n' > "${LOG_FILE}"
    exit 0
    ;;
  *)
    printf 'unknown verification mode: %s\n' "${VERIFY_MODE}" > "${LOG_FILE}"
    TEST_TARGETS=(tests/test_auth.py tests/test_navigation_ia.py)
    ;;
esac

if "${PYTHON}" -m pytest -q "${TEST_TARGETS[@]}" > "${LOG_FILE}" 2>&1; then
  printf 'PASSED %s mode=%s log=%s backup=%s\n' "$(date --iso-8601=seconds)" "${VERIFY_MODE}" "${LOG_FILE}" "${BACKUP_PATH}" > "${STATUS_FILE}"
  exit 0
fi

printf '\nPost-deploy %s tests failed. Starting automatic rollback.\n' "${VERIFY_MODE}" >> "${LOG_FILE}"
if "${APP_DIR}/deployment/rollback_dashboard.sh" "${BACKUP_PATH}" >> "${LOG_FILE}" 2>&1; then
  touch "${APP_DIR}/app.py" /var/www/casino_shingoon_me_wsgi.py /var/www/www_casinoin_kr_wsgi.py
  printf 'ROLLED_BACK %s log=%s backup=%s\n' "$(date --iso-8601=seconds)" "${LOG_FILE}" "${BACKUP_PATH}" > "${STATUS_FILE}"
else
  printf 'ROLLBACK_FAILED %s log=%s backup=%s\n' "$(date --iso-8601=seconds)" "${LOG_FILE}" "${BACKUP_PATH}" > "${STATUS_FILE}"
fi
exit 1

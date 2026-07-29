"""Collect and cache oil-price and exchange-rate data."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard_db import queries
from extensions import dashboard_db
from services import economic_data, sync_alerts
from utils import setup_logger

logger = setup_logger("economic_data_sync")


def run():
    connection = dashboard_db()
    run_id = queries.start_analysis_run(connection, "economic_data_sync")
    try:
        results = (economic_data.fetch_oil(), economic_data.fetch_exchange())
        items = [item for result in results for item in result["items"]]
        errors = [error for result in results for error in result["errors"]]
        for item in items:
            queries.upsert_economic_observation(connection, item)
        status = "success" if not errors else ("partial_failure" if items else "failed")
        detail = "; ".join(errors[:10]) if errors else None
        queries.finish_analysis_run(connection, run_id, status, detail)
        for error in errors:
            queries.log_error(connection, "economic_data_sync", "external_api", error)
        sync_alerts.notify_issue("economic_data_sync", status, errors)
        logger.info("유가·환율 동기화 완료: 저장 %d건, 오류 %d건", len(items), len(errors))
    except Exception as error:
        queries.log_error(connection, "economic_data_sync", type(error).__name__, str(error))
        queries.finish_analysis_run(connection, run_id, "failed", str(error))
        sync_alerts.notify_issue("economic_data_sync", "failed", str(error))
        logger.exception("유가·환율 동기화 실패")
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    run()

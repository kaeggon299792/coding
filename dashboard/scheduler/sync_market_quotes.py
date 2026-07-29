"""금융위원회 주식·지수 시세를 대시보드 캐시에 저장한다."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard_db import queries  # noqa: E402
from extensions import dashboard_db  # noqa: E402
from services import market_data  # noqa: E402
from utils import setup_logger  # noqa: E402

logger = setup_logger("market_quote_sync")


def run():
    connection = dashboard_db()
    run_id = queries.start_analysis_run(connection, "market_quote_sync")
    try:
        result = market_data.fetch_dashboard_quotes()
        for quote in result["quotes"]:
            queries.upsert_market_quote(connection, quote)
        errors = [error for error in result["errors"] if error]
        for error in errors:
            queries.log_error(connection, "market_quote_sync", "market_api", error)
        status = "success" if not errors else ("partial_failure" if result["quotes"] else "failed")
        detail = "; ".join(sorted(set(errors))) if errors else None
        queries.finish_analysis_run(connection, run_id, status, detail)
        logger.info(
            "시장 시세 동기화 완료: 저장 %d건, 오류 %d건",
            len(result["quotes"]), len(errors),
        )
    except Exception as error:
        logger.error("시장 시세 동기화 실패: %s", error)
        queries.log_error(connection, "market_quote_sync", type(error).__name__, str(error))
        queries.finish_analysis_run(connection, run_id, "failed", str(error))
    finally:
        connection.close()


if __name__ == "__main__":
    run()

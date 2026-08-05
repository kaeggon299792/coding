"""카지노 운영 법인의 연봉·평점·국민연금 고용지표를 일 1회 누적한다."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard_db import queries  # noqa: E402
from extensions import dashboard_db  # noqa: E402
from services import salary_data, sync_alerts  # noqa: E402
from utils import setup_logger  # noqa: E402

logger = setup_logger("salary_sync")


def run():
    connection = dashboard_db()
    run_id = queries.start_analysis_run(connection, "salary_sync")
    try:
        result = salary_data.fetch_all()
        for item in result["items"]:
            queries.upsert_salary_snapshot(connection, item)
        for review in result["reviews"]:
            queries.upsert_employer_review_snapshot(connection, review)
        for item in result["employment_metrics"]:
            queries.upsert_employment_metric_snapshot(connection, item)
        errors = [
            f"{item['entity_code']}: {item['error']}" for item in result["errors"]
        ]
        status = "success" if not errors else (
            "partial_failure" if result["items"] else "failed"
        )
        detail = "; ".join(errors) if errors else None
        queries.finish_analysis_run(connection, run_id, status, detail)
        sync_alerts.notify_issue("salary_sync", status, errors)
        logger.info(
            "연봉·평점 정보 동기화 완료: 연봉 %d건, 평점 %d건, 공개자료 없음 %d건, 오류 %d건",
            len(result["items"]), len(result["reviews"]),
            len(result.get("missing", [])), len(errors),
        )
    except Exception as error:
        queries.finish_analysis_run(connection, run_id, "failed", str(error))
        sync_alerts.notify_issue("salary_sync", "failed", str(error))
        logger.exception("연봉 정보 동기화 실패")
    finally:
        connection.close()


if __name__ == "__main__":
    run()

"""채용 사이트 공고를 수집하고 신규 공고를 AI 분석한다."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard_db import queries  # noqa: E402
import config  # noqa: E402
from extensions import dashboard_db  # noqa: E402
from services import recruitment_data, sync_alerts  # noqa: E402
from utils import now_kst, setup_logger  # noqa: E402

logger = setup_logger("recruitment_sync")


def run():
    connection = dashboard_db()
    run_id = queries.start_analysis_run(connection, "recruitment_sync")
    try:
        result = recruitment_data.fetch_all()
        ai_count = 0
        for item in result["items"]:
            existing = connection.execute(
                "SELECT id, analyzed_at FROM recruitment_jobs "
                "WHERE source_name=? AND source_job_id=?",
                (item["source_name"], item["source_job_id"]),
            ).fetchone()
            if ((not existing or not existing["analyzed_at"])
                    and ai_count < config.RECRUITMENT_AI_MAX_PER_RUN):
                analysis, error = recruitment_data.analyze_with_ai(connection, item)
                item.update(analysis)
                item["analysis_error"] = error
                item["analyzed_at"] = now_kst().isoformat() if not error else None
                ai_count += 1
            queries.upsert_recruitment_job(connection, item)
        errors = result["errors"]
        status = "success" if not errors else (
            "partial_failure" if result["items"] else "failed"
        )
        queries.finish_analysis_run(
            connection, run_id, status, "; ".join(errors) if errors else None
        )
        sync_alerts.notify_issue("recruitment_sync", status, errors)
        logger.info("채용 동기화 완료: 저장 %d건, 오류 %d건",
                    len(result["items"]), len(errors))
    except Exception as error:
        queries.finish_analysis_run(connection, run_id, "failed", str(error))
        sync_alerts.notify_issue("recruitment_sync", "failed", str(error))
        logger.exception("채용 동기화 실패")
    finally:
        connection.close()


if __name__ == "__main__":
    run()

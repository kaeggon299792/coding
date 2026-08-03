"""최근 DART 공시 중 AI 요약이 없거나 실패한 항목을 다시 분석한다."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from dashboard_db import queries  # noqa: E402
from extensions import dashboard_db  # noqa: E402
from services import ai_insights  # noqa: E402
from utils import setup_logger  # noqa: E402

logger = setup_logger("disclosure_backfill")


def run(days=30, limit=100):
    connection = dashboard_db()
    try:
        rows = connection.execute(
            """
            SELECT d.*
            FROM dart_disclosures d
            WHERE d.rcept_dt >= strftime('%Y%m%d', 'now', ?)
              AND NOT EXISTS (
                SELECT 1 FROM disclosure_analysis a
                WHERE a.disclosure_id = d.id
                  AND a.ai_summary IS NOT NULL
                  AND trim(a.ai_summary) <> ''
                  AND a.error_message IS NULL
              )
            ORDER BY d.rcept_dt DESC, d.id DESC
            LIMIT ?
            """,
            (f"-{max(1, int(days))} days", max(1, int(limit))),
        ).fetchall()
        success_count = 0
        error_count = 0
        for row in rows:
            item = dict(row)
            summary = ai_insights.summarize_disclosure(connection, item)
            error = summary.get("error")
            queries.save_disclosure_analysis(
                connection,
                item["id"],
                ai_summary=summary.get("ai_summary"),
                importance="high" if item.get("is_important") else "routine",
                financial_impact=summary.get("financial_impact"),
                competitive_impact=summary.get("competitive_impact"),
                risk_category=summary.get("risk_category"),
                needs_executive_review=summary.get("needs_executive_review", bool(item.get("is_important"))),
                prompt_version=config.AI_DISCLOSURE_PROMPT_VERSION,
                error_message=error,
            )
            if error:
                error_count += 1
                logger.error("공시 AI 분석 실패(%s): %s", item["rcept_no"], error)
            else:
                success_count += 1
        logger.info(
            "공시 AI 요약 보완 완료: 대상 %d건, 성공 %d건, 오류 %d건",
            len(rows), success_count, error_count,
        )
        return success_count, error_count
    finally:
        connection.close()


if __name__ == "__main__":
    run()

"""
PythonAnywhere Scheduled Task 진입점 (1일 1회, 뉴스/이메일 수집 이후 시간대 권장).

오늘의 중요 뉴스 + 임원 확인 필요 이메일 + 오늘 실적 데이터를 모아 AI에게
경영진 관점 시사점을 생성하도록 요청하고 executive_insights에 저장한다.
페이지를 열 때마다 재분석하지 않고 하루 1회만 실행한다(스펙 12절).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from dashboard_db import queries  # noqa: E402
from extensions import dashboard_db  # noqa: E402
from services import ai_insights, email_reader, news_reader  # noqa: E402
from utils import setup_logger, today_kst_str  # noqa: E402

logger = setup_logger("daily_insight_batch")


def _build_context_text(connection, today):
    news_items = news_reader.today_important_articles()[:15]
    email_items = email_reader.today_important_emails()[:15]
    performance = queries.get_latest_performance_report(connection, today)

    lines = [f"기준일: {today}", ""]

    lines.append(f"## 오늘의 중요 뉴스 ({len(news_items)}건)")
    if news_items:
        for item in news_items:
            lines.append(
                f"- [{item.get('category') or '미분류'}] {item.get('title')} "
                f"(중요도점수 {item.get('importance_score')}) - "
                f"{item.get('latest_summary') or '요약 없음'}"
            )
    else:
        lines.append("- 없음")
    lines.append("")

    lines.append(f"## 임원 확인 필요 이메일 ({len(email_items)}건)")
    if email_items:
        for item in email_items:
            lines.append(
                f"- [{item.get('importance')}] {item.get('subject')} "
                f"(발신: {item.get('sender_name') or item.get('sender_address')}) - "
                f"{item.get('summary') or '요약 없음'}"
            )
    else:
        lines.append("- 없음")
    lines.append("")

    lines.append("## 오늘 실적(텔레그램 데이터랩 알림 기준, 일부 지표만 확인 가능)")
    if performance and performance.get("parsed"):
        parsed = performance["parsed"]
        for key, value in parsed.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- 오늘 파싱된 실적 데이터 없음")

    return "\n".join(lines)


def run():
    connection = dashboard_db()
    today = today_kst_str()
    run_id = queries.start_analysis_run(connection, "daily_insight", config.AI_INSIGHT_PROMPT_VERSION)

    try:
        if queries.count_insights_for_date(connection, today) > 0:
            logger.info("오늘(%s) 시사점이 이미 생성되어 있어 건너뜁니다.", today)
            queries.finish_analysis_run(connection, run_id, "skipped_already_done")
            return

        context_text = _build_context_text(connection, today)
        insights, error = ai_insights.generate_daily_insights(connection, context_text)

        if error:
            logger.error("경영진 시사점 생성 실패: %s", error)
            queries.log_error(connection, "daily_insight_batch", "ai_insights", error)
            queries.finish_analysis_run(connection, run_id, "failed", error)
            return

        for insight in insights:
            queries.create_executive_insight(
                connection,
                insight_date=today,
                title=insight["title"],
                importance=insight["importance"],
                evidence=insight.get("evidence_refs", []),
                facts=insight["facts"],
                ai_interpretation=insight["ai_interpretation"],
                expected_impact=insight["expected_impact"],
                recommended_action=insight["recommended_action"],
                needs_executive_review=insight["needs_executive_review"],
                category=insight["category"],
                prompt_version=config.AI_INSIGHT_PROMPT_VERSION,
            )

        logger.info("경영진 시사점 %d건 생성 완료", len(insights))
        queries.finish_analysis_run(connection, run_id, "success")

    except Exception as error:
        logger.error("일일 시사점 배치 실패: %s", error)
        queries.log_error(connection, "daily_insight_batch", type(error).__name__, str(error))
        queries.finish_analysis_run(connection, run_id, "failed", str(error))
    finally:
        connection.close()


if __name__ == "__main__":
    run()

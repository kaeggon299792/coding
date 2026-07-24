"""
PythonAnywhere Scheduled Task 진입점 (평일 업무시간 1시간 간격 권장).

관심기업(monitored_companies)의 최근 공시를 증분 수집하고, 중요 공시로 판정되면
AI 요약을 생성한 뒤 텔레그램 긴급 알림을 보낸다. 일반 공시는 대시보드에만 누적된다.

DART_API_KEY가 없거나 DART 서버 호출이 실패해도 이전에 저장된 공시 데이터는
그대로 표시되며, 이 실행만 건너뛴다(대시보드 전체 장애로 번지지 않음).
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from dashboard_db import queries  # noqa: E402
from extensions import dashboard_db  # noqa: E402
from services import ai_insights, dart_client, telegram_alert  # noqa: E402
from utils import now_kst, setup_logger  # noqa: E402

logger = setup_logger("dart_sync")


def _build_alert_message(disclosure_row, ai_summary):
    lines = [
        "🏢 중요 공시 발생",
        "",
        f"기업: {disclosure_row['corp_name']}",
        f"공시명: {disclosure_row['report_nm']}",
        f"접수일: {disclosure_row['rcept_dt']}",
    ]
    if ai_summary:
        lines.append("")
        lines.append(f"AI 요약: {ai_summary}")
    lines.append("")
    lines.append(disclosure_row["dart_link"])
    return "\n".join(lines)


def run():
    connection = dashboard_db()
    run_id = queries.start_analysis_run(connection, "dart_sync")

    try:
        if not config.DART_API_KEY:
            raise RuntimeError("DART_API_KEY가 설정되지 않았습니다.")

        companies = queries.list_monitored_companies(connection, active_only=True)
        if not companies:
            logger.warning("등록된 관심기업(monitored_companies)이 없습니다. 동기화를 건너뜁니다.")
            queries.finish_analysis_run(connection, run_id, "success")
            return

        end_date = now_kst().strftime("%Y%m%d")
        start_date = (now_kst() - timedelta(days=config.DART_SYNC_LOOKBACK_DAYS)).strftime("%Y%m%d")

        new_count = 0
        error_count = 0

        for company in companies:
            corp_code = company["dart_corp_code"]
            if not corp_code:
                continue

            result = dart_client.search_disclosures(
                corp_code=corp_code, start_date=start_date, end_date=end_date, page_count=100
            )
            if not result.get("ok"):
                logger.error("공시검색 실패(%s): %s", company["name"], result.get("error"))
                queries.log_error(connection, "dart_sync", "search_disclosures", result.get("error", ""))
                error_count += 1
                continue

            for item in result.get("list", []):
                rcept_no = item.get("rcept_no")
                if not rcept_no or queries.disclosure_exists(connection, rcept_no):
                    continue

                report_nm = item.get("report_nm", "")
                is_important = dart_client.is_important_disclosure(report_nm)

                disclosure_id = queries.save_disclosure(
                    connection,
                    rcept_no=rcept_no,
                    corp_name=item.get("corp_name"),
                    dart_corp_code=corp_code,
                    report_nm=report_nm,
                    pblntf_ty=item.get("pblntf_ty"),
                    rcept_dt=item.get("rcept_dt"),
                    flr_nm=item.get("flr_nm"),
                    dart_link=dart_client.build_dart_link(rcept_no),
                    is_important=is_important,
                )
                new_count += 1

                if is_important:
                    summary = ai_insights.summarize_disclosure(connection, {
                        "corp_name": item.get("corp_name"),
                        "report_nm": report_nm,
                        "rcept_dt": item.get("rcept_dt"),
                        "flr_nm": item.get("flr_nm"),
                    })
                    queries.save_disclosure_analysis(
                        connection, disclosure_id,
                        ai_summary=summary.get("ai_summary"),
                        importance="high",
                        financial_impact=summary.get("financial_impact"),
                        competitive_impact=summary.get("competitive_impact"),
                        risk_category=summary.get("risk_category"),
                        needs_executive_review=summary.get("needs_executive_review", True),
                        prompt_version=config.AI_DISCLOSURE_PROMPT_VERSION,
                        error_message=summary.get("error"),
                    )

                    row = dict(item)
                    row["corp_name"] = item.get("corp_name")
                    row["report_nm"] = report_nm
                    row["rcept_dt"] = item.get("rcept_dt")
                    row["dart_link"] = dart_client.build_dart_link(rcept_no)
                    sent = telegram_alert.send_alert(_build_alert_message(row, summary.get("ai_summary")))
                    if sent:
                        queries.mark_disclosure_alert_sent(connection, disclosure_id)

        logger.info("DART 동기화 완료: 신규 공시 %d건, 기업 조회 오류 %d건", new_count, error_count)
        queries.finish_analysis_run(
            connection, run_id, "success" if error_count == 0 else "partial_failure"
        )

    except Exception as error:
        logger.error("DART 동기화 실패: %s", error)
        queries.log_error(connection, "dart_sync", type(error).__name__, str(error))
        queries.finish_analysis_run(connection, run_id, "failed", str(error))
    finally:
        connection.close()


if __name__ == "__main__":
    run()

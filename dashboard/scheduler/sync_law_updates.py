"""
PythonAnywhere Scheduled Task 진입점 (1일 1회 권장).

monitored_laws에 등록된 법령의 공포된 원문을 조회해 이전 스냅샷과 조문 해시를
비교한다. 변경이 없으면 AI 분석을 실행하지 않는다(스펙 7절: 불필요한 AI 호출
금지). 변경이 감지된 경우에만 AI 요약 + 텔레그램 알림을 실행한다.

범위 한계: 이 작업은 "공포된 법령 원문의 변경"만 감지한다. 발의/심사 중인
법안의 진행 단계 추적은 국회 의안정보시스템 등 별도 API가 필요해 이번 범위에
포함하지 않았다(law_client.py 상단 주석 참고).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from dashboard_db import queries  # noqa: E402
from extensions import dashboard_db  # noqa: E402
from services import ai_insights, assembly_bill_client, economic_data, government_notice_client, law_client, market_data, telegram_alert  # noqa: E402
from utils import setup_logger  # noqa: E402

logger = setup_logger("law_sync")


def _build_alert_message(law_name, status, effective_date, ai_summary):
    lines = [
        "⚖️ 모니터링 법령 변경 감지",
        "",
        f"법령명: {law_name}",
        f"상태: {status}",
        f"시행일자: {effective_date or '확인 필요'}",
    ]
    if ai_summary:
        lines.append("")
        lines.append(f"AI 요약: {ai_summary}")
    return "\n".join(lines)


def _ensure_mst(connection, law_row):
    """Resolve the latest exact law version, retaining the saved MST on API failure."""
    search_result = law_client.search_law(law_row["law_name"])
    if not search_result.get("ok") or not search_result.get("candidates"):
        return law_row.get("mst")

    best = law_client.select_exact_candidate(
        search_result["candidates"], law_row["law_name"]
    )
    if not best:
        return law_row.get("mst")

    if str(best.get("mst")) == str(law_row.get("mst")):
        return law_row.get("mst")

    queries.upsert_monitored_law(
        connection, law_row["law_name"], law_id=best.get("law_id"), mst=best.get("mst")
    )
    return best.get("mst")


def _build_bill_alert(bill):
    return "\n".join([
        "🏛️ 카지노 관련 신규 입법 의안",
        "",
        f"의안명: {bill['bill_name']}",
        f"제안자: {bill.get('proposer_name') or '-'}",
        f"제안일: {bill.get('proposed_date') or '-'}",
        f"진행상태: {bill.get('process_stage') or bill.get('pass_status') or '확인 필요'}",
        f"바로가기: {bill.get('link_url') or '-'}",
    ])


def _sync_assembly_bills(connection):
    if not config.ASSEMBLY_API_KEY:
        logger.warning("ASSEMBLY_API_KEY가 없어 국회 의안정보 확인을 건너뜁니다.")
        return 0, 0

    new_count = 0
    error_count = 0
    seen_ids = set()
    has_baseline = bool(queries.list_legislative_bills(connection, limit=1))
    for keyword in config.ASSEMBLY_BILL_KEYWORDS:
        result = assembly_bill_client.search_bills(keyword)
        if not result.get("ok"):
            logger.error("의안정보 검색 실패(%s): %s", keyword, result.get("error"))
            queries.log_error(
                connection, "law_sync", "assembly_bill_search",
                f"{keyword}: {result.get('error', '')}",
            )
            error_count += 1
            continue

        for row in result.get("bills", []):
            bill = assembly_bill_client.normalize_bill(row, keyword)
            if not bill.get("bill_id") or not bill.get("bill_name"):
                continue
            if bill["bill_id"] in seen_ids:
                continue
            seen_ids.add(bill["bill_id"])
            if queries.upsert_legislative_bill(connection, bill):
                new_count += 1
                if has_baseline:
                    telegram_alert.send_alert(_build_bill_alert(bill))

    return new_count, error_count


def _build_government_notice_alert(notice):
    return "\n".join([
        "📢 카지노 관련 정부입법예고",
        "",
        f"예고명: {notice['notice_name']}",
        f"소관부처: {notice.get('ministry_name') or '-'}",
        f"의견제출기간: {notice.get('start_date') or '-'} ~ {notice.get('end_date') or '-'}",
        f"바로가기: {notice.get('detail_url') or '-'}",
    ])


def _sync_government_notices(connection):
    new_count = 0
    error_count = 0
    seen_ids = set()
    has_baseline = bool(
        queries.list_government_legislative_notices(connection, limit=1)
    )
    for keyword in config.LAWMAKING_NOTICE_KEYWORDS:
        result = government_notice_client.search_notices(keyword)
        if not result.get("ok"):
            logger.error(
                "정부입법예고 검색 실패(%s): %s", keyword, result.get("error")
            )
            queries.log_error(
                connection, "law_sync", "government_notice_search",
                f"{keyword}: {result.get('error', '')}",
            )
            error_count += 1
            continue
        for node in result.get("notices", []):
            notice = government_notice_client.normalize_notice(node, keyword)
            if (
                not notice.get("notice_id")
                or not notice.get("notice_name")
                or notice["notice_id"] in seen_ids
            ):
                continue
            seen_ids.add(notice["notice_id"])
            if queries.upsert_government_legislative_notice(connection, notice):
                new_count += 1
                if has_baseline:
                    telegram_alert.send_alert(
                        _build_government_notice_alert(notice)
                    )
    return new_count, error_count


def _analyze_pending_bills(connection):
    analyzed_count = 0
    error_count = 0
    pending = queries.list_pending_legislative_bill_analysis(
        connection, limit=config.ASSEMBLY_AI_MAX_PER_RUN
    )
    for bill in pending:
        source = assembly_bill_client.fetch_bill_source_text(
            bill["bill_id"], bill.get("bill_kind")
        )
        if not source.get("ok"):
            queries.save_legislative_bill_analysis(
                connection, bill["id"], error=source.get("error")
            )
            error_count += 1
            continue
        result = ai_insights.analyze_legislative_bill(
            connection, bill, source["text"]
        )
        if result.get("error") or not result.get("analysis"):
            queries.save_legislative_bill_analysis(
                connection, bill["id"], error=result.get("error") or "AI 분석 결과 없음"
            )
            error_count += 1
            continue
        queries.save_legislative_bill_analysis(
            connection,
            bill["id"],
            analysis=result["analysis"],
            source=source.get("source"),
        )
        analyzed_count += 1
    return analyzed_count, error_count


def _sync_market_quotes(connection):
    result = market_data.fetch_dashboard_quotes()
    global_result = market_data.fetch_global_quotes()
    result["quotes"].extend(global_result["quotes"])
    result["errors"].extend(
        f"{item.get('symbol')}: {item.get('error')}"
        for item in global_result["errors"]
    )
    for quote in result["quotes"]:
        queries.upsert_market_quote(connection, quote)
        queries.upsert_market_quote_history(
            connection, quote["symbol"], quote.get("history") or []
        )
    for error in result["errors"]:
        queries.log_error(connection, "market_quote_sync", "market_api", error)
    for failure in global_result["errors"]:
        queries.mark_market_quote_failure(
            connection, failure.get("symbol"), failure.get("error")
        )
    return len(result["quotes"]), len(result["errors"])


def _sync_economic_series(connection):
    results = (economic_data.fetch_oil(), economic_data.fetch_exchange())
    items = [item for result in results for item in result["items"]]
    errors = [error for result in results for error in result["errors"]]
    for item in items:
        queries.upsert_economic_observation(connection, item)
    return len(items), len(errors)


def run():
    connection = dashboard_db()
    run_id = queries.start_analysis_run(connection, "law_sync")

    try:
        if not (config.LAW_API_OC and config.LAW_API_KEY):
            raise RuntimeError("LAW_API_OC / LAW_API_KEY가 설정되지 않았습니다.")

        laws = queries.list_monitored_laws(connection, active_only=True)
        if not laws:
            logger.warning("등록된 monitored_laws가 없습니다. 동기화를 건너뜁니다.")
            queries.finish_analysis_run(connection, run_id, "success")
            return

        changed_count = 0
        error_count = 0

        for law_row in laws:
            mst = _ensure_mst(connection, law_row)
            if not mst:
                logger.error("'%s' 법령의 MST를 찾지 못했습니다.", law_row["law_name"])
                error_count += 1
                continue

            text_result = law_client.get_law_text(mst)
            if not text_result.get("ok"):
                public_result = law_client.get_public_law_metadata(law_row["law_name"])
                if not public_result.get("ok"):
                    logger.error("'%s' 법령 본문 조회 실패: %s", law_row["law_name"], text_result.get("error"))
                    queries.log_error(connection, "law_sync", "get_law_text", text_result.get("error", ""))
                    error_count += 1
                    continue

                public_mst = str(public_result["mst"])
                if public_mst == str(law_row.get("mst")):
                    continue

                queries.upsert_monitored_law(
                    connection, law_row["law_name"], law_id=law_row.get("law_id"),
                    mst=public_mst,
                )
                previous_hash = queries.get_latest_law_snapshot_hash(connection, law_row["id"])
                status = "변경 감지(재확인 필요)" if previous_hash else "시행 중"
                queries.save_law_update(
                    connection,
                    monitored_law_id=law_row["id"],
                    snapshot_hash=f"mst:{public_mst}",
                    effective_date=public_result.get("effective_date"),
                    promulgation_date=public_result.get("promulgation_date"),
                    status=status,
                    raw_summary={
                        "effective_date": public_result.get("effective_date"),
                        "promulgation_date": public_result.get("promulgation_date"),
                        "source": "public_law_page",
                    },
                )
                changed_count += 1
                if previous_hash is not None:
                    telegram_alert.send_alert(
                        _build_alert_message(
                            law_row["law_name"], status,
                            public_result.get("effective_date"), None,
                        )
                    )
                continue

            law_data = text_result["law"]
            snapshot_hash = law_client.compute_snapshot_hash(law_data)
            previous_hash = queries.get_latest_law_snapshot_hash(connection, law_row["id"])

            if previous_hash == snapshot_hash:
                continue  # 변경 없음 - AI 분석 실행하지 않음

            dates = law_client.extract_dates(law_data)
            status = "시행 중" if not previous_hash else "변경 감지(재확인 필요)"

            law_update_id = queries.save_law_update(
                connection,
                monitored_law_id=law_row["id"],
                snapshot_hash=snapshot_hash,
                effective_date=dates.get("effective_date"),
                promulgation_date=dates.get("promulgation_date"),
                status=status,
                raw_summary=dates,
            )
            changed_count += 1

            if previous_hash is not None:
                # 최초 수집(기준점 저장)은 알림 없이 저장만 하고, 그 다음부터의 변경만 알린다.
                summary = ai_insights.summarize_law_change(connection, {
                    "law_name": law_row["law_name"],
                    "status": status,
                    "effective_date": dates.get("effective_date"),
                })
                queries.save_law_analysis(
                    connection, law_update_id,
                    ai_summary=summary.get("ai_summary"),
                    affected_scope=summary.get("affected_scope"),
                    company_impact=summary.get("company_impact"),
                    action_needed=summary.get("action_needed"),
                    prompt_version=config.AI_LAW_PROMPT_VERSION,
                    error_message=summary.get("error"),
                )
                telegram_alert.send_alert(
                    _build_alert_message(
                        law_row["law_name"], status, dates.get("effective_date"), summary.get("ai_summary")
                    )
                )

        new_bill_count, bill_error_count = _sync_assembly_bills(connection)
        error_count += bill_error_count
        new_notice_count, notice_error_count = _sync_government_notices(connection)
        error_count += notice_error_count
        analyzed_bill_count, analysis_error_count = _analyze_pending_bills(connection)
        market_count, market_error_count = _sync_market_quotes(connection)
        economic_count, economic_error_count = _sync_economic_series(connection)
        logger.info(
            "법률정보 동기화 완료: 법령 변경 %d건, 신규 관련 의안 %d건, "
            "신규 정부입법예고 %d건, "
            "의안 AI 분석 %d건, 시장 시세 %d건, 오류 %d건",
            changed_count, new_bill_count, new_notice_count, analyzed_bill_count,
            market_count, error_count + analysis_error_count + market_error_count + economic_error_count,
        )
        queries.finish_analysis_run(connection, run_id, "success" if error_count == 0 else "partial_failure")

    except Exception as error:
        logger.error("법률정보 동기화 실패: %s", error)
        queries.log_error(connection, "law_sync", type(error).__name__, str(error))
        queries.finish_analysis_run(connection, run_id, "failed", str(error))
    finally:
        connection.close()


if __name__ == "__main__":
    run()

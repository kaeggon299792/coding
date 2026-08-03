"""Common notifications for scheduled external-data sync failures."""

from services import telegram_alert


LABELS = {
    "economic_data_sync": "유가·환율",
    "tourism_stats_sync": "관광객 통계",
    "market_quote_sync": "주가·지수",
    "dart_sync": "DART 공시",
    "law_sync": "법률·의안",
}


def notify_issue(run_type, status, errors):
    if status == "success":
        return True
    details = errors if isinstance(errors, str) else "; ".join(
        str(item) for item in errors if item
    )
    return telegram_alert.send_alert(
        "\n".join([
            "⚠️ 외부 데이터 동기화 확인 필요",
            "",
            f"작업: {LABELS.get(run_type, run_type)}",
            f"상태: {status}",
            f"오류: {(details or '상세 오류 없음')[:1200]}",
            "",
            "기존 정상 데이터는 유지됩니다.",
        ]),
        force=True,
    )

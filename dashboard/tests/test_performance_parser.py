from services import performance_parser
from dashboard_db import queries
import sqlite3


def test_parses_big_change_message():
    text = (
        "🚨 데이터랩 매출 큰 폭 변동\n"
        "2026-07-24 09:08 기준\n\n"
        "그룹 매출: 5,127백만원 (전일 대비 158.8%)\n"
        "전일: 1,981백만원\n"
        "카지노: 4,228백만원\n"
        "호텔 & 리조트: 900백만원\n"
        "워커힐: 1,332백만원"
    )
    parsed, error = performance_parser.parse(text)
    assert error is None
    assert parsed.header_type == "big_change"
    assert parsed.captured_at_text == "2026-07-24 09:08"
    assert parsed.fields["group_sales_today"] == "5,127백만원"
    assert parsed.fields["change_percent"] == "158.8%"
    assert parsed.fields["group_sales_yesterday"] == "1,981백만원"
    assert parsed.fields["casino_sales"] == "4,228백만원"
    assert parsed.fields["hotel_resort_sales"] == "900백만원"
    assert parsed.fields["walkerhill_sales"] == "1,332백만원"


def test_parses_summary_message_without_walkerhill():
    text = (
        "📊 데이터랩 주요지표 요약\n"
        "2026-07-24 10:00 기준\n\n"
        "그룹 매출: 3,000백만원 (전일 대비 5.2%)\n"
        "전일: 2,850백만원\n"
        "카지노: 2,000백만원\n"
        "호텔 & 리조트: 1,000백만원"
    )
    parsed, error = performance_parser.parse(text)
    assert error is None
    assert parsed.header_type == "summary"
    assert "walkerhill_sales" not in parsed.fields


def test_parses_no_change_message_with_partial_fields_only():
    text = (
        "📊 데이터랩 주요지표: 이전과 변화없음\n"
        "2026-07-24 11:00 기준\n\n"
        "그룹 매출: 3,000백만원 (전일 대비 0.0%)"
    )
    parsed, error = performance_parser.parse(text)
    assert error is None
    assert parsed.header_type == "no_change"
    assert parsed.fields["group_sales_today"] == "3,000백만원"
    # 없는 지표를 임의로 채우지 않는다
    assert "casino_sales" not in parsed.fields
    assert "hotel_resort_sales" not in parsed.fields


def test_capture_failed_header_returns_empty_fields_without_error():
    text = "📊 데이터랩 주요지표\n2026-07-24 12:00 기준"
    parsed, error = performance_parser.parse(text)
    assert error is None
    assert parsed.header_type == "capture_failed"
    assert parsed.fields == {}


def test_unrelated_message_is_ignored_not_a_parsing_failure():
    text = "📌 카지노·관광 변화 알림\n\n이슈: 어떤 뉴스 제목\n중요도: 높음"
    parsed, error = performance_parser.parse(text)
    assert parsed is None
    assert error is None  # 데이터랩 메시지가 아니므로 저장 대상 자체가 아님


def test_header_recognized_but_body_format_changed_is_a_parsing_failure():
    text = "🚨 데이터랩 매출 큰 폭 변동\n완전히 다른 형식으로 바뀐 본문입니다."
    parsed, error = performance_parser.parse(text)
    assert parsed is None
    assert error is not None


def test_builds_30_day_casino_sales_trend_from_latest_daily_reports():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE performance_reports (
            report_date TEXT, received_at TEXT, parsed_json TEXT, parsing_status TEXT
        )
        """
    )
    connection.executemany(
        "INSERT INTO performance_reports VALUES (?, ?, ?, 'ok')",
        [
            ("2026-07-27", "2026-07-27T09:00:00", '{"casino_sales":"1,851백만원"}'),
            ("2026-07-28", "2026-07-28T08:00:00", '{"casino_sales":"100백만원"}'),
            ("2026-07-28", "2026-07-28T09:00:00", '{"casino_sales":"-64백만원"}'),
            ("2026-07-29", "2026-07-29T08:30:00", '{"casino_sales":"-572백만원"}'),
            ("2026-06-01", "2026-06-01T09:00:00", '{"casino_sales":"9,999백만원"}'),
        ],
    )

    trend = queries.get_casino_sales_trend(connection, "2026-07-29", days=30)

    assert [entry["value"] for entry in trend["entries"]] == [1851, -64, -572]
    assert trend["latest"]["value"] == -572
    assert trend["highest"]["value"] == 1851
    assert trend["lowest"]["value"] == -572
    assert trend["day_count"] == 3

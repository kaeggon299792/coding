from dashboard_db import queries
from services import telegram_ingest


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _no_webhook(monkeypatch):
    monkeypatch.setattr(
        "requests.get",
        lambda url, **kwargs: FakeResponse({"ok": True, "result": {"url": ""}})
        if "getWebhookInfo" in url
        else None,
    )


def test_webhook_conflict_blocks_polling(monkeypatch, db_connection):
    monkeypatch.setattr(
        "requests.get",
        lambda url, **kwargs: FakeResponse({"ok": True, "result": {"url": "https://example.com/hook"}}),
    )
    saved = telegram_ingest.poll_once(db_connection)
    assert saved == 0
    errors = db_connection.execute("SELECT * FROM errors").fetchall()
    assert len(errors) == 1
    assert errors[0]["stage"] == "telegram_ingest"


def test_datalab_message_is_saved_and_offset_advances(monkeypatch, db_connection):
    def fake_get(url, **kwargs):
        if "getWebhookInfo" in url:
            return FakeResponse({"ok": True, "result": {"url": ""}})
        if "getUpdates" in url:
            return FakeResponse({
                "ok": True,
                "result": [
                    {
                        "update_id": 100,
                        "message": {
                            "message_id": 5001,
                            "date": 1721800000,
                            "chat": {"id": -1},
                            "photo": [{"file_id": "abc"}],
                            "caption": (
                                "🚨 데이터랩 매출 큰 폭 변동\n2026-07-24 09:08 기준\n\n"
                                "그룹 매출: 5,127백만원 (전일 대비 158.8%)\n전일: 1,981백만원\n"
                                "카지노: 4,228백만원\n호텔 & 리조트: 900백만원"
                            ),
                        },
                    }
                ],
            })
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("requests.get", fake_get)

    saved = telegram_ingest.poll_once(db_connection)
    assert saved == 1
    assert queries.get_last_update_id(db_connection) == 100

    reports = db_connection.execute("SELECT * FROM performance_reports").fetchall()
    assert len(reports) == 1
    assert reports[0]["parsing_status"] == "ok"
    assert reports[0]["message_kind"] == "photo"


def test_non_datalab_message_in_same_chat_is_ignored(monkeypatch, db_connection):
    def fake_get(url, **kwargs):
        if "getWebhookInfo" in url:
            return FakeResponse({"ok": True, "result": {"url": ""}})
        if "getUpdates" in url:
            return FakeResponse({
                "ok": True,
                "result": [
                    {
                        "update_id": 200,
                        "message": {
                            "message_id": 6001,
                            "date": 1721800000,
                            "chat": {"id": -1},
                            "text": "📌 카지노·관광 변화 알림\n\n이슈: 어떤 뉴스",
                        },
                    }
                ],
            })
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("requests.get", fake_get)

    saved = telegram_ingest.poll_once(db_connection)
    assert saved == 0
    # 오프셋은 진행되어야 다음에 같은 업데이트를 반복해서 받지 않는다.
    assert queries.get_last_update_id(db_connection) == 200
    reports = db_connection.execute("SELECT * FROM performance_reports").fetchall()
    assert len(reports) == 0


def test_duplicate_message_id_is_not_stored_twice(db_connection):
    queries.save_performance_report(
        db_connection, report_date="2026-07-24", telegram_update_id=1, telegram_message_id=9001,
        telegram_chat_id="-1", message_kind="text", header_type="summary", raw_text="원문",
        parsed_data={"group_sales_today": "1,000백만원"}, parsing_status="ok", parsing_error=None,
        received_at="2026-07-24T09:00:00+09:00",
    )
    queries.save_performance_report(
        db_connection, report_date="2026-07-24", telegram_update_id=1, telegram_message_id=9001,
        telegram_chat_id="-1", message_kind="text", header_type="summary", raw_text="원문(중복 수신)",
        parsed_data={"group_sales_today": "9,999백만원"}, parsing_status="ok", parsing_error=None,
        received_at="2026-07-24T09:00:05+09:00",
    )
    reports = db_connection.execute("SELECT * FROM performance_reports").fetchall()
    assert len(reports) == 1

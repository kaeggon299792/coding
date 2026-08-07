import json
import sqlite3

from services import content_translation


def _connection():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE content_translations (
            id INTEGER PRIMARY KEY, content_type TEXT, content_id TEXT,
            locale TEXT, source_hash TEXT, translated_json TEXT, status TEXT,
            error_message TEXT, translated_at TEXT, updated_at TEXT,
            UNIQUE(content_type, content_id, locale)
        )"""
    )
    return connection


def test_source_hash_changes_with_source_text():
    first = content_translation.source_hash({"title": "원문"})
    second = content_translation.source_hash({"title": "수정 원문"})
    assert first != second


def test_apply_cached_uses_only_matching_successful_translation():
    connection = _connection()
    item = {"id": 1, "title": "제목", "summary": "요약", "body": "본문",
            "category": "기타", "tags_json": "[]"}
    entry = content_translation.make_entry("tip", 1, item)
    connection.execute(
        """INSERT INTO content_translations
           VALUES (1, 'tip', '1', 'en', ?, ?, 'success', NULL, '', '')""",
        (entry["source_hash"], json.dumps({"title": "Title", "body": "Body"})),
    )
    translated = content_translation.apply_one(connection, "tip", item)
    assert translated["title"] == "Title"
    assert translated["body"] == "Body"

    changed = dict(item, title="새 제목")
    assert content_translation.apply_one(connection, "tip", changed)["title"] == "새 제목"


def test_failed_refresh_preserves_previous_json_but_marks_error():
    connection = _connection()
    old = {"content_type": "tip", "content_id": "1", "source_hash": "old"}
    content_translation._save(connection, old, translated={"title": "Old"})
    changed = {"content_type": "tip", "content_id": "1", "source_hash": "new"}
    content_translation._save(connection, changed, error="temporary failure")
    row = connection.execute("SELECT * FROM content_translations").fetchone()
    assert row["status"] == "error"
    assert json.loads(row["translated_json"])["title"] == "Old"


def test_cjk_source_fallbacks_are_masked_on_english_pages():
    items = [
        {
            "title": "한국어 제목",
            "category": "기업 동향",
            "latest_summary": "한국어 요약",
            "publisher": "example.com",
        },
        {
            "title": "Already translated",
            "category": "Market",
            "latest_summary": "English summary",
        },
    ]

    masked = content_translation.mask_cjk_fallbacks(
        items,
        {
            "title": "English translation pending",
            "category": "Uncategorized",
            "latest_summary": "",
        },
    )

    assert masked[0]["title"] == "English translation pending"
    assert masked[0]["category"] == "Uncategorized"
    assert masked[0]["latest_summary"] == ""
    assert masked[0]["publisher"] == "example.com"
    assert masked[1] == items[1]

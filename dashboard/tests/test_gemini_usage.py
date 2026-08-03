import sqlite3

import pytest

import config
from services import gemini_news, gemini_usage


def _connection():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE economic_series (
            series_code TEXT, observation_date TEXT, value REAL
        );
        INSERT INTO economic_series VALUES ('FX_USD', '2026-08-01', 1380.5);
        CREATE TABLE overseas_news_articles (
            id INTEGER PRIMARY KEY, title_ko TEXT, canonical_url TEXT, publisher TEXT
        );
        INSERT INTO overseas_news_articles VALUES (
            7, '마카오 카지노 매출 증가', 'https://example.com/news', 'Example'
        );
        CREATE TABLE api_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            called_at TEXT NOT NULL, model TEXT, request_type TEXT,
            input_tokens INTEGER, output_tokens INTEGER, estimated_cost REAL,
            success INTEGER NOT NULL, provider TEXT, article_id INTEGER,
            article_title TEXT, article_url TEXT, request_stage TEXT,
            thought_tokens INTEGER DEFAULT 0, total_tokens INTEGER DEFAULT 0,
            search_query_count INTEGER DEFAULT 0, input_cost_usd REAL DEFAULT 0,
            output_cost_usd REAL DEFAULT 0, search_cost_usd REAL DEFAULT 0,
            usd_krw_rate REAL, estimated_cost_krw REAL DEFAULT 0
        );
        """
    )
    return connection


def test_usage_record_counts_thinking_and_unique_nonempty_search_queries(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_INPUT_COST_PER_1M_USD", 1.5)
    monkeypatch.setattr(config, "GEMINI_OUTPUT_COST_PER_1M_USD", 9.0)
    monkeypatch.setattr(config, "GEMINI_SEARCH_COST_PER_1000_USD", 14.0)
    payload = {
        "usageMetadata": {
            "promptTokenCount": 1_000,
            "candidatesTokenCount": 200,
            "thoughtsTokenCount": 300,
            "totalTokenCount": 1_500,
        },
        "candidates": [{"groundingMetadata": {"webSearchQueries": ["Macau", "", "Macau", "Japan"]}}],
    }

    usage = gemini_news._usage_record(payload, "grounded_search")

    assert usage["input_tokens"] == 1_000
    assert usage["output_tokens"] == 200
    assert usage["thought_tokens"] == 300
    assert usage["search_query_count"] == 2
    assert usage["input_cost_usd"] == pytest.approx(0.0015)
    assert usage["output_cost_usd"] == pytest.approx(0.0045)
    assert usage["search_cost_usd"] == pytest.approx(0.028)


def test_article_usage_is_stored_and_aggregated_with_latest_exchange_rate():
    connection = _connection()
    usage = {
        "request_stage": "grounded_search",
        "model": "gemini-test",
        "input_tokens": 1000,
        "output_tokens": 200,
        "thought_tokens": 300,
        "total_tokens": 1500,
        "search_query_count": 2,
        "input_cost_usd": 0.0015,
        "output_cost_usd": 0.0045,
        "search_cost_usd": 0.028,
        "estimated_cost_usd": 0.034,
    }
    article = {
        "id": 7,
        "original_title": "Macau casino revenue rises",
        "original_url": "https://example.com/news",
    }

    count = gemini_usage.record_article_usage(
        connection, article, [usage], called_at="2026-08-01T10:20:30+09:00"
    )
    connection.commit()
    dashboard = gemini_usage.admin_dashboard(connection)

    assert count == 1
    row = connection.execute("SELECT * FROM api_usage").fetchone()
    assert row["provider"] == "gemini"
    assert row["article_id"] == 7
    assert row["usd_krw_rate"] == 1380.5
    assert round(row["estimated_cost_krw"], 4) == round(0.034 * 1380.5, 4)
    assert dashboard["all_time"]["search_query_count"] == 2
    assert dashboard["recent_articles"][0]["article_title"] == "마카오 카지노 매출 증가"

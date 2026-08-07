import sqlite3
from types import SimpleNamespace

from services import overseas_news


def _connection():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE overseas_news_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT, article_key TEXT NOT NULL UNIQUE,
            region TEXT NOT NULL, original_title TEXT NOT NULL, original_summary TEXT,
            title_ko TEXT, summary_ko TEXT, publisher TEXT, original_url TEXT NOT NULL,
            source_feed TEXT NOT NULL, published_at TEXT, collected_at TEXT NOT NULL,
            translated_at TEXT, translation_status TEXT NOT NULL DEFAULT 'pending',
            translation_error TEXT, category TEXT, impact_direction TEXT,
            importance_score INTEGER, ai_analysis TEXT, analyzed_at TEXT,
            canonical_url TEXT, analysis_basis TEXT, retrieval_status TEXT,
            source_citations_json TEXT, gemini_model TEXT,
            gemini_analyzed_at TEXT, analysis_error TEXT,
            analysis_provider TEXT, analysis_model TEXT, web_verified_at TEXT
        );
        CREATE TABLE overseas_news_sync_state (
            id INTEGER PRIMARY KEY CHECK (id=1), last_checked_at TEXT,
            last_changed_at TEXT, last_status TEXT, last_error TEXT, updated_at TEXT NOT NULL
        );
        CREATE TABLE site_settings (
            setting_key TEXT PRIMARY KEY, setting_value TEXT,
            updated_by INTEGER, updated_at TEXT
        );
        """
    )
    return connection


def test_fetch_feed_removes_google_publisher_suffix(monkeypatch):
    xml = b"""<?xml version='1.0' encoding='UTF-8'?>
    <rss><channel><item><title>Macau casino revenue rises - Test News</title>
    <link>https://news.google.com/rss/articles/example</link>
    <pubDate>Fri, 01 Aug 2026 01:00:00 GMT</pubDate>
    <source>Test News</source><description>Macau casino revenue rises</description>
    </item></channel></rss>"""
    response = SimpleNamespace(content=xml, status_code=200, raise_for_status=lambda: None)
    monkeypatch.setattr(overseas_news, "get_with_hard_timeout", lambda *args, **kwargs: response)
    rows = overseas_news._fetch_feed(overseas_news.FEEDS[0])
    assert rows[0]["original_title"] == "Macau casino revenue rises"
    assert rows[0]["publisher"] == "Test News"
    assert rows[0]["original_summary"] == ""


def test_sync_deduplicates_and_caches_korean_translation(monkeypatch):
    connection = _connection()
    article = {
        "article_key": "same-key",
        "region": "macau",
        "original_title": "Macau casino revenue rises",
        "original_summary": "",
        "publisher": "Test News",
        "original_url": "https://example.com/article",
        "source_feed": "https://news.google.com/",
        "published_at": "2026-08-01T01:00:00+00:00",
    }
    monkeypatch.setattr(overseas_news, "FEEDS", ({"region": "macau", "label": "마카오"},))
    monkeypatch.setattr(overseas_news, "_fetch_feed", lambda *args, **kwargs: [article, article])
    monkeypatch.setattr(overseas_news.config, "OPENAI_NEWS_MAX_PER_RUN", 30)
    monkeypatch.setattr(overseas_news.config, "OPENAI_NEWS_WEB_IMPORTANCE_THRESHOLD", 90)
    monkeypatch.setattr(overseas_news.ai_insights, "translate_overseas_news_batch", lambda connection, items: ({
        str(items[0]["id"]): {
            "title_ko": "마카오 카지노 매출 증가", "summary_ko": "RSS 일괄 요약",
            "category": "실적·시장", "impact_direction": "positive",
            "importance_score": 75, "ai_analysis": "시장 회복 여부를 확인할 필요가 있습니다.",
        }
    }, None))
    first = overseas_news.sync(connection)
    second = overseas_news.sync(connection)
    assert first["inserted"] == 1
    assert first["translated"] == 1
    assert second["inserted"] == 0
    assert connection.execute("SELECT COUNT(*) FROM overseas_news_articles").fetchone()[0] == 1
    row = connection.execute("SELECT title_ko, translation_status, analysis_basis FROM overseas_news_articles").fetchone()
    assert row["title_ko"] == "마카오 카지노 매출 증가"
    assert row["translation_status"] == "translated"
    assert row["analysis_basis"] == "rss_batch"


def test_only_important_news_uses_bounded_web_search(monkeypatch):
    connection = _connection()
    for index, score in enumerate((95, 90, 50), 1):
        connection.execute(
            """INSERT INTO overseas_news_articles
               (article_key, region, original_title, publisher, original_url,
                source_feed, collected_at, translation_status)
               VALUES (?, 'macau', ?, 'Source', ?, 'feed', datetime('now'), 'pending')""",
            (f"key-{index}", f"Headline {index}", f"https://example.com/{index}"),
        )
    monkeypatch.setattr(overseas_news.config, "OPENAI_NEWS_BATCH_SIZE", 10)
    monkeypatch.setattr(overseas_news.config, "OPENAI_NEWS_WEB_IMPORTANCE_THRESHOLD", 75)
    monkeypatch.setattr(overseas_news.config, "OPENAI_NEWS_WEB_MAX_PER_RUN", 1)

    def batch_analysis(connection, items):
        return {
            str(item["id"]): {
                "title_ko": f"번역 {item['id']}", "summary_ko": "요약",
                "category": "실적·시장", "impact_direction": "neutral",
                "importance_score": (100 - int(item["id"]) * 5), "ai_analysis": "분석",
            }
            for item in items
        }, None

    searched = []
    monkeypatch.setattr(overseas_news.ai_insights, "translate_overseas_news_batch", batch_analysis)
    monkeypatch.setattr(
        overseas_news.ai_insights,
        "analyze_important_overseas_news_with_web",
        lambda connection, item: (searched.append(item["id"]) or {
            "title_ko": "웹 검증", "summary_ko": "검증 요약", "category": "실적·시장",
            "impact_direction": "positive", "importance_score": 98,
            "ai_analysis": "검증 분석", "canonical_url": "https://publisher.example/story",
            "source_urls": ["https://publisher.example/story"],
        }, None),
    )
    analyzed, errors = overseas_news._analyze_pending(connection, limit=3)
    assert analyzed == 3
    assert errors == []
    assert len(searched) == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM overseas_news_articles WHERE analysis_basis='web_search'"
    ).fetchone()[0] == 1


def test_list_filters_region_and_searches_korean_title():
    connection = _connection()
    connection.executemany(
        """
        INSERT INTO overseas_news_articles (
            article_key, region, original_title, title_ko, publisher, original_url,
            source_feed, published_at, collected_at, translation_status,
            category, impact_direction, importance_score, ai_analysis
        ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), 'translated', ?, ?, ?, ?)
        """,
        [
            ("a", "macau", "Macau gaming", "마카오 카지노 매출", "A", "https://a", "feed", "실적·시장", "positive", 70, "회복 신호"),
            ("b", "japan", "Osaka IR", "오사카 복합리조트", "B", "https://b", "feed", "복합리조트 개발", "neutral", 55, "개발 일정 확인"),
        ],
    )
    rows = overseas_news.list_articles(connection, region="japan", term="오사카")
    assert len(rows) == 1
    assert rows[0]["region"] == "japan"
    assert overseas_news.count_articles(connection, important_only=True) == 1
    assert overseas_news.list_articles(connection, impact="positive")[0]["article_key"] == "a"


def test_list_ai_insights_only_returns_analyzed_articles_and_follows_filters():
    connection = _connection()
    connection.executemany(
        """
        INSERT INTO overseas_news_articles (
            article_key, region, original_title, title_ko, publisher, original_url,
            source_feed, published_at, collected_at, translation_status,
            category, impact_direction, importance_score, ai_analysis
        ) VALUES (?, ?, ?, ?, ?, ?, 'feed', ?, datetime('now'), 'translated', ?, ?, ?, ?)
        """,
        [
            ("latest", "japan", "Latest", "최근 분석", "A", "https://a", "2026-08-07 09:00:00", "시장", "positive", 80, "최근 AI 분석"),
            ("older", "japan", "Older", "이전 분석", "B", "https://b", "2026-08-06 09:00:00", "시장", "neutral", 60, "이전 AI 분석"),
            ("pending", "japan", "Pending", "분석 대기", "C", "https://c", "2026-08-07 10:00:00", "시장", "neutral", 40, None),
            ("macau", "macau", "Macau", "마카오 분석", "D", "https://d", "2026-08-07 08:00:00", "규제", "negative", 90, "마카오 AI 분석"),
        ],
    )

    rows = overseas_news.list_ai_insights(
        connection, days=365, region="japan", category="시장", limit=2
    )

    assert [row["article_key"] for row in rows] == ["latest", "older"]
    assert all(row["ai_analysis"] for row in rows)
    assert rows[0]["display_url"] == "https://a"


def test_important_filter_uses_admin_threshold():
    connection = _connection()
    connection.executemany(
        """INSERT INTO overseas_news_articles (
               article_key,region,original_title,publisher,original_url,source_feed,
               collected_at,translation_status,importance_score,ai_analysis
           ) VALUES (?,'macau',?,'A',?,'feed',datetime('now'),'translated',?,'분석')""",
        [
            ("score-70", "Score 70", "https://a", 70),
            ("score-80", "Score 80", "https://b", 80),
        ],
    )
    connection.execute(
        """INSERT INTO site_settings(setting_key,setting_value,updated_at)
           VALUES ('ai_purpose_news_importance_importance_threshold','75',datetime('now'))"""
    )
    assert overseas_news.count_articles(connection, important_only=True) == 1
    assert overseas_news.stats(connection)["important_count"] == 1


def test_manual_analysis_updates_only_selected_article_and_bypasses_limit(monkeypatch):
    connection = _connection()
    connection.executemany(
        """INSERT INTO overseas_news_articles (
               article_key,region,original_title,publisher,original_url,source_feed,
               collected_at,translation_status
           ) VALUES (?,'japan',?,'Source',?,'feed',datetime('now'),'pending')""",
        [
            ("manual-1", "Osaka casino update", "https://example.com/1"),
            ("manual-2", "Another article", "https://example.com/2"),
        ],
    )
    calls = []

    def translate(_connection, items, *, bypass_daily_limits=False):
        calls.append((items[0]["id"], bypass_daily_limits))
        return {
            str(items[0]["id"]): {
                "title_ko": "오사카 카지노 업데이트",
                "summary_ko": "기사 요약",
                "category": "규제·정책",
                "impact_direction": "neutral",
                "importance_score": 40,
                "ai_analysis": "추가 확인이 필요합니다.",
            }
        }, None

    monkeypatch.setattr(overseas_news.ai_insights, "translate_overseas_news_batch", translate)
    result, error = overseas_news.analyze_article(
        connection, 1, bypass_daily_limits=True
    )

    assert error is None
    assert result["importance_score"] == 40
    assert calls == [(1, True)]
    analyzed = connection.execute(
        "SELECT title_ko,ai_analysis,analysis_basis FROM overseas_news_articles WHERE id=1"
    ).fetchone()
    assert analyzed["title_ko"] == "오사카 카지노 업데이트"
    assert analyzed["ai_analysis"] == "추가 확인이 필요합니다."
    assert analyzed["analysis_basis"] == "rss_manual"
    untouched = connection.execute(
        "SELECT ai_analysis FROM overseas_news_articles WHERE id=2"
    ).fetchone()
    assert untouched["ai_analysis"] is None


def test_manual_analysis_failure_is_saved_for_retry(monkeypatch):
    connection = _connection()
    connection.execute(
        """INSERT INTO overseas_news_articles (
               article_key,region,original_title,publisher,original_url,source_feed,
               collected_at,translation_status
           ) VALUES ('manual-error','macau','Headline','Source','https://example.com',
                     'feed',datetime('now'),'pending')"""
    )
    monkeypatch.setattr(
        overseas_news.ai_insights,
        "translate_overseas_news_batch",
        lambda *args, **kwargs: (None, "provider unavailable"),
    )

    result, error = overseas_news.analyze_article(connection, 1)

    assert result is None
    assert error == "provider unavailable"
    row = connection.execute(
        "SELECT translation_status,analysis_error FROM overseas_news_articles WHERE id=1"
    ).fetchone()
    assert row["translation_status"] == "retry"
    assert row["analysis_error"] == "provider unavailable"

import sqlite3

from services import news_reader


def _news_connection(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def test_list_articles_includes_stored_ai_analysis(monkeypatch, tmp_path):
    database = tmp_path / "news.db"
    connection = _news_connection(database)
    connection.executescript(
        """
        CREATE TABLE issues (
          issue_id INTEGER PRIMARY KEY, issue_key TEXT, issue_title TEXT,
          category TEXT, first_seen_at TEXT, last_seen_at TEXT, importance TEXT,
          impact_direction TEXT, latest_summary TEXT, sent_at TEXT,
          updated_at TEXT, representative_normalized_title TEXT
        );
        CREATE TABLE articles (
          article_id INTEGER PRIMARY KEY, normalized_url TEXT, original_url TEXT,
          normalized_title TEXT, title TEXT, publisher TEXT, published_at TEXT,
          collected_at TEXT, content_hash TEXT, status TEXT, relevance_score INTEGER,
          importance_score INTEGER, issue_id INTEGER, sent_at TEXT
        );
        INSERT INTO issues (
          issue_id, issue_title, category, first_seen_at, last_seen_at,
          importance, impact_direction, latest_summary
        ) VALUES (
          1, '카지노 제도 변화', '법률·규제', datetime('now'), datetime('now'),
          'high', 'negative', '영업 규제 강화 가능성을 점검해야 합니다.'
        );
        INSERT INTO articles (
          article_id, original_url, title, publisher, published_at, collected_at,
          status, relevance_score, importance_score, issue_id
        ) VALUES (
          1, 'https://example.com/news', '카지노 제도 관련 뉴스', '테스트뉴스',
          datetime('now'), datetime('now'), 'collected', 90, 80, 1
        );
        """
    )
    connection.commit()
    connection.close()
    monkeypatch.setattr(
        news_reader, "news_db_readonly", lambda: _news_connection(database)
    )

    rows = news_reader.list_articles(
        days=30, term="제도", impact_direction="negative", important_only=True
    )
    assert len(rows) == 1
    assert rows[0]["latest_summary"].startswith("영업 규제")
    assert news_reader.article_stats(30)["analyzed_count"] == 1
    assert news_reader.list_categories(30)[0]["category"] == "법률·규제"


def test_entertainment_news_is_hidden_by_default_but_can_be_included(monkeypatch, tmp_path):
    database = tmp_path / "entertainment.db"
    connection = _news_connection(database)
    connection.executescript(
        """
        CREATE TABLE issues (issue_id INTEGER PRIMARY KEY, issue_key TEXT, issue_title TEXT,
          category TEXT, first_seen_at TEXT, last_seen_at TEXT, importance TEXT,
          impact_direction TEXT, latest_summary TEXT, sent_at TEXT, updated_at TEXT,
          representative_normalized_title TEXT);
        CREATE TABLE articles (article_id INTEGER PRIMARY KEY, normalized_url TEXT,
          original_url TEXT, normalized_title TEXT, title TEXT, publisher TEXT,
          published_at TEXT, collected_at TEXT, content_hash TEXT, status TEXT,
          relevance_score INTEGER, importance_score INTEGER, issue_id INTEGER, sent_at TEXT);
        INSERT INTO issues (issue_id, category) VALUES (1, '연예');
        INSERT INTO articles (article_id, original_url, title, collected_at, issue_id)
        VALUES (1, 'https://example.com/celebrity', '인기 배우 열애 소식', datetime('now'), 1);
        """
    )
    connection.commit(); connection.close()
    monkeypatch.setattr(news_reader, "news_db_readonly", lambda: _news_connection(database))
    assert news_reader.list_articles(days=30) == []
    assert len(news_reader.list_articles(days=30, include_entertainment=True)) == 1
    assert news_reader.count_filtered_articles(days=30) == 0

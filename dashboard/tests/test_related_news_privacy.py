from pathlib import Path


def test_public_related_news_never_queries_or_renders_internal_insights(monkeypatch, tmp_path):
    import app as app_module
    from dashboard_db import schema

    database = tmp_path / "privacy.db"
    connection = schema.connect(str(database))
    connection.close()
    monkeypatch.setattr(app_module, "dashboard_db", lambda: schema.connect(str(database)))
    monkeypatch.setattr(app_module.news_reader, "count_filtered_articles", lambda **kwargs: 0)
    monkeypatch.setattr(app_module.news_reader, "list_articles", lambda **kwargs: [])
    monkeypatch.setattr(app_module.news_reader, "list_categories", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        app_module.news_reader,
        "article_stats",
        lambda *args, **kwargs: {"total_count": 0, "analyzed_count": 0, "important_count": 0, "negative_count": 0},
    )
    monkeypatch.setattr(app_module.news_reader, "last_updated_at", lambda: None)

    def forbidden_query(*args, **kwargs):
        raise AssertionError("public route attempted to read internal executive insights")

    monkeypatch.setattr(app_module.queries, "list_recent_executive_insights", forbidden_query)
    monkeypatch.setitem(app_module.app.config, "TESTING", True)
    monkeypatch.setitem(app_module.app.config, "SERVER_NAME", None)
    response = app_module.app.test_client().get("/news", base_url="https://localhost")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "경영진 관점 분석" not in page
    assert "AI 관점" not in page
    assert "AI 분석" in page


def test_daily_ai_analysis_does_not_load_telegram_performance_context():
    root = Path(__file__).resolve().parents[1]
    batch = (root / "scheduler" / "daily_insight_batch.py").read_text(encoding="utf-8")
    service = (root / "services" / "ai_insights.py").read_text(encoding="utf-8")

    assert "get_latest_performance_report" not in batch
    assert "오늘 실적" not in batch
    assert "텔레그램 실적이나 내부 성과 데이터는 분석하지 마세요" in service


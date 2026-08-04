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
    assert "경영진 관점 분석" not in response.get_data(as_text=True)


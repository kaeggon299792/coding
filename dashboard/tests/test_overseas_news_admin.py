import pytest


@pytest.fixture
def overseas_admin_client(monkeypatch, tmp_path):
    import app as app_module
    import config
    from dashboard_db import schema

    db_path = tmp_path / "overseas-admin.db"
    monkeypatch.setattr(config, "DASHBOARD_DB_FILE", str(db_path))
    app_module.app.config.update(TESTING=True)
    connection = schema.connect(str(db_path))
    admin = connection.execute(
        """INSERT INTO dashboard_users
           (username,password_hash,role,membership_level,is_active,approval_status,created_at)
           VALUES ('news-admin','unused','admin','black',1,'approved',datetime('now'))"""
    ).lastrowid
    user = connection.execute(
        """INSERT INTO dashboard_users
           (username,password_hash,role,membership_level,is_active,approval_status,created_at)
           VALUES ('news-user','unused','user','gold',1,'approved',datetime('now'))"""
    ).lastrowid
    article = connection.execute(
        """INSERT INTO overseas_news_articles
           (article_key,region,original_title,publisher,original_url,source_feed,
            published_at,collected_at,translation_status)
           VALUES ('route-article','japan','Osaka IR update','Publisher',
                   'https://example.com/article','feed',datetime('now'),datetime('now'),'pending')"""
    ).lastrowid
    connection.commit()
    connection.close()
    return app_module, app_module.app.test_client(), db_path, admin, user, article


def _login(client, user_id, username, role, token):
    with client.session_transaction() as session:
        session.update(
            user_id=user_id, username=username, role=role, csrf_token=token
        )


def test_analysis_button_is_visible_only_to_admin(overseas_admin_client):
    _, client, _, admin, user, article = overseas_admin_client
    route = f"/news/overseas/{article}/analyze"

    assert route not in client.get("/news/overseas").get_data(as_text=True)
    _login(client, user, "news-user", "user", "u" * 64)
    assert route not in client.get("/news/overseas").get_data(as_text=True)
    _login(client, admin, "news-admin", "admin", "a" * 64)
    html = client.get("/news/overseas").get_data(as_text=True)
    assert route in html
    assert "AI 분석" in html


def test_public_page_has_separate_ai_analysis_panel(overseas_admin_client):
    _, client, db_path, _, _, article = overseas_admin_client
    from dashboard_db import schema

    connection = schema.connect(str(db_path))
    connection.execute(
        """UPDATE overseas_news_articles
           SET title_ko='오사카 IR 업데이트', ai_analysis='해외뉴스 AI 분석 결과',
               category='시장', impact_direction='positive'
           WHERE id=?""",
        (article,),
    )
    connection.commit()
    connection.close()

    html = client.get("/news/overseas").get_data(as_text=True)

    assert 'class="insight-feed overseas-insight-feed"' in html
    assert 'id="overseas-ai-insights-title">AI 분석</h2>' in html
    assert "해외뉴스 AI 분석 결과" in html


def test_research_company_checkboxes_keep_compact_dimensions():
    from pathlib import Path

    css = (Path(__file__).parents[1] / "static" / "css" / "dashboard.css").read_text(
        encoding="utf-8"
    )

    assert '.company-multi-select input[type="checkbox"]' in css
    assert "flex:0 0 16px" in css
    assert "min-height:0" in css


def test_analysis_route_requires_admin_and_csrf(overseas_admin_client):
    _, client, _, admin, user, article = overseas_admin_client
    route = f"/news/overseas/{article}/analyze"

    _login(client, user, "news-user", "user", "u" * 64)
    assert client.post(route, data={"csrf_token": "u" * 64}).status_code == 403
    _login(client, admin, "news-admin", "admin", "a" * 64)
    assert client.post(route, data={"csrf_token": "wrong"}).status_code == 400


def test_admin_can_run_analysis_for_one_article(monkeypatch, overseas_admin_client):
    app_module, client, db_path, admin, _, article = overseas_admin_client
    calls = []

    def analyze(connection, article_id, *, bypass_daily_limits=False):
        calls.append((article_id, bypass_daily_limits))
        connection.execute(
            """UPDATE overseas_news_articles
               SET ai_analysis='manual result',translation_status='translated'
               WHERE id=?""",
            (article_id,),
        )
        connection.commit()
        return {"ai_analysis": "manual result"}, None

    monkeypatch.setattr(app_module.overseas_news, "analyze_article", analyze)
    _login(client, admin, "news-admin", "admin", "a" * 64)
    response = client.post(
        f"/news/overseas/{article}/analyze",
        data={"csrf_token": "a" * 64},
    )

    assert response.status_code == 302
    assert response.location.endswith(f"/news/overseas#overseas-news-{article}")
    assert calls == [(article, True)]

    from dashboard_db import schema
    connection = schema.connect(str(db_path))
    try:
        audit = connection.execute(
            """SELECT action,success FROM security_audit_log
               WHERE resource_type='overseas_news_article' AND resource_id=?""",
            (str(article),),
        ).fetchone()
        assert audit["action"] == "OVERSEAS_NEWS_AI_ANALYSIS"
        assert audit["success"] == 1
    finally:
        connection.close()

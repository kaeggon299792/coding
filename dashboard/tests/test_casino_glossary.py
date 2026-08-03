from dashboard_db import schema


def test_glossary_schema_seeds_game_and_business_terms(tmp_path):
    connection = schema.connect(str(tmp_path / "glossary-schema.db"))
    rows = connection.execute(
        "SELECT category, COUNT(*) AS count FROM casino_glossary_terms GROUP BY category"
    ).fetchall()
    assert {row["category"] for row in rows} == {"game", "business"}
    assert sum(row["count"] for row in rows) >= 20
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    connection.close()


def test_glossary_is_public_but_registration_is_admin_csrf_protected(monkeypatch, tmp_path):
    db_path = tmp_path / "glossary-routes.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))

    import app as app_module

    connection = schema.connect(str(db_path))
    admin_id = connection.execute(
        """INSERT INTO dashboard_users
               (username, password_hash, role, is_active, created_at)
           VALUES ('glossary-admin', 'unused', 'admin', 1, '2026-08-04T00:00:00')"""
    ).lastrowid
    connection.commit()
    connection.close()

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        public = client.get("/tips/glossary")
        assert public.status_code == 200
        assert "카지노 용어집" in public.get_data(as_text=True)
        assert "바카라" in public.get_data(as_text=True)
        assert client.post("/tips/glossary", data={}).status_code == 403

        with client.session_transaction() as browser_session:
            browser_session["user_id"] = admin_id
            browser_session["username"] = "glossary-admin"
            browser_session["role"] = "admin"
            browser_session["csrf_token"] = "g" * 64

        assert client.post("/tips/glossary", data={}).status_code == 400
        created = client.post(
            "/tips/glossary",
            data={
                "csrf_token": "g" * 64,
                "category": "game",
                "term_ko": "테스트 게임 용어",
                "term_en": "Test Gaming Term",
                "definition": "기본 의미입니다.",
                "easy_explanation": "쉽게 풀어쓴 설명입니다.",
                "aliases": "테스트, 예시",
                "is_public": "1",
            },
        )
        assert created.status_code == 302

    connection = schema.connect(str(db_path))
    row = connection.execute(
        "SELECT * FROM casino_glossary_terms WHERE term_ko=?",
        ("테스트 게임 용어",),
    ).fetchone()
    assert row["term_en"] == "Test Gaming Term"
    assert row["is_public"] == 1
    connection.close()


def test_glossary_subnav_and_english_static_labels(monkeypatch, tmp_path):
    db_path = tmp_path / "glossary-en.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    schema.connect(str(db_path)).close()

    import app as app_module

    app_module.app.config["TESTING"] = True
    response = app_module.app.test_client().get("/en/tips/glossary")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Casino Glossary" in html
    assert "Gaming Terms" in html
    assert "Business Terms" in html
    assert 'href="/en/tips/glossary"' in html

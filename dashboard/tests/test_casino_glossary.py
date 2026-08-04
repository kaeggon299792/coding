from dashboard_db import schema


def test_glossary_schema_seeds_game_and_business_terms(tmp_path):
    from dashboard_db.glossary_operations_terms import CASINO_GLOSSARY_OPERATIONS_TERMS

    connection = schema.connect(str(tmp_path / "glossary-schema.db"))
    rows = connection.execute(
        "SELECT category, COUNT(*) AS count FROM casino_glossary_terms GROUP BY category"
    ).fetchall()
    assert {row["category"] for row in rows} == {"game", "business"}
    assert sum(row["count"] for row in rows) >= 20
    assert connection.execute(
        "SELECT category FROM casino_glossary_terms WHERE term_en='Electronic Table Game, ETG'"
    ).fetchone()["category"] == "game"
    assert connection.execute(
        "SELECT category FROM casino_glossary_terms WHERE term_en='Casino Host'"
    ).fetchone()["category"] == "business"
    assert connection.execute(
        "SELECT COUNT(*) FROM casino_glossary_terms WHERE term_en='Chip'"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT category FROM casino_glossary_terms WHERE term_en='Customer Acquisition Cost, CAC'"
    ).fetchone()["category"] == "business"
    assert connection.execute(
        "SELECT easy_explanation FROM casino_glossary_terms WHERE term_ko='일평균 이론승액'"
    ).fetchone()[0] == "고객 하루 이용 기준 예상수익입니다."
    etg_terms = connection.execute(
        """SELECT term_ko, term_en FROM casino_glossary_terms
           WHERE term_ko IN (
               '전자 테이블 게임', 'ETG 드롭', 'ETG 턴오버', 'ETG 승액',
               'ETG 홀드율', '단말기당 승액', '단말기 가동률',
               '좌석 점유율', '시간당 게임 수'
           )"""
    ).fetchall()
    assert len(etg_terms) == 9
    assert dict(etg_terms)["전자 테이블 게임"] == "Electronic Table Game, ETG"
    assert dict(etg_terms)["시간당 게임 수"] == "Decisions per Hour"
    operations_terms = connection.execute(
        """SELECT term_ko, term_en FROM casino_glossary_terms
           WHERE term_ko IN ('출납', '드롭박스', '크레딧 한도', '환전장부',
                             '머신게임', '거래 모니터링')"""
    ).fetchall()
    assert len(operations_terms) == 6
    assert dict(operations_terms)["출납"] == "Cashiering / Cage Operations"
    assert dict(operations_terms)["거래 모니터링"] == "Transaction Monitoring"
    assert len(CASINO_GLOSSARY_OPERATIONS_TERMS) == 114
    assert len({term[1] for term in CASINO_GLOSSARY_OPERATIONS_TERMS}) == 114
    for _, term_ko, term_en, definition, easy_explanation in CASINO_GLOSSARY_OPERATIONS_TERMS:
        stored = connection.execute(
            """SELECT term_en, definition, easy_explanation
               FROM casino_glossary_terms WHERE term_ko=? AND is_deleted=0""",
            (term_ko,),
        ).fetchone()
        assert stored is not None
        assert tuple(stored) == (term_en, definition, easy_explanation)
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
    delete_term_id = connection.execute(
        "SELECT id FROM casino_glossary_terms WHERE term_ko='바카라'"
    ).fetchone()["id"]
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

        admin_page = client.get("/tips/glossary")
        assert f'name="csrf_token" value="{"g" * 64}"' in admin_page.get_data(as_text=True)
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
        duplicate = client.post(
            "/tips/glossary",
            data={
                "csrf_token": "g" * 64,
                "category": "business",
                "term_ko": "테스트 게임 용어",
                "term_en": "Duplicate Term",
                "definition": "중복 정의입니다.",
                "easy_explanation": "중복 설명입니다.",
                "is_public": "1",
            },
        )
        assert duplicate.status_code == 302
        deleted = client.post(
            f"/tips/glossary/{delete_term_id}/delete",
            data={"csrf_token": "g" * 64},
            follow_redirects=True,
        )
        deleted_html = deleted.get_data(as_text=True)
        assert deleted.status_code == 200
        assert deleted_html.count("카지노 용어를 삭제했습니다.") == 1
        new_tip_page = client.get("/tips/new").get_data(as_text=True)
        assert "카지노 용어를 삭제했습니다." not in new_tip_page

    connection = schema.connect(str(db_path))
    row = connection.execute(
        "SELECT * FROM casino_glossary_terms WHERE term_ko=?",
        ("테스트 게임 용어",),
    ).fetchone()
    assert row["term_en"] == "Test Gaming Term"
    assert row["is_public"] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM casino_glossary_terms WHERE term_ko=?",
        ("테스트 게임 용어",),
    ).fetchone()[0] == 1
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
    template = (__import__("pathlib").Path(__file__).parents[1] / "templates" / "tips" / "glossary.html").read_text(encoding="utf-8")
    assert '{% include "_data_subnav.html" %}' in template
    assert 'tips/_subnav.html' not in template

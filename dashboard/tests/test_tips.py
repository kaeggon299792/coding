from services import tips_content


def test_import_preserves_portfolio_fields_and_is_idempotent(db_connection):
    records = [{
        "id": "abc123def456",
        "slug": "excel-shortcut",
        "title": "Excel 단축키",
        "summary": "업무 시간을 줄이는 단축키",
        "category": "Excel",
        "tags": ["Excel", "자동화"],
        "date": "2026-07-01",
        "updated": "2026-07-02",
        "readingTime": "3분",
        "featured": True,
        "draft": False,
        "coverImage": "/static/img/tip.png",
        "body": "## 본문\n\n```python\nprint('safe')\n```",
    }]

    assert tips_content.import_portfolio_records(db_connection, records) == (1, 0)
    assert tips_content.import_portfolio_records(db_connection, records) == (0, 1)
    item = tips_content.get_tip(db_connection, "excel-shortcut")
    assert item["id"] == "abc123def456"
    assert item["tags"] == ["Excel", "자동화"]
    assert item["featured"] is True
    assert item["reading_time"] == "3분"


def test_search_includes_title_summary_body_and_filters_category(db_connection):
    tips_content.save_tip(db_connection, {
        "title": "파이썬 자동화",
        "body": "본문에만 있는 영종도 키워드",
        "category": "Python",
    }, None)
    tips_content.save_tip(db_connection, {
        "title": "엑셀 함수",
        "body": "VLOOKUP 설명",
        "category": "Excel",
    }, None)

    assert [item["title"] for item in tips_content.list_tips(
        db_connection, query="영종도"
    )] == ["파이썬 자동화"]
    assert [item["category"] for item in tips_content.list_tips(
        db_connection, category="Excel"
    )] == ["Excel"]


def test_draft_visibility_soft_delete_and_restore(db_connection):
    item = tips_content.save_tip(db_connection, {
        "title": "관리자 초안", "body": "비공개", "draft": True,
    }, None)
    assert tips_content.get_tip(db_connection, item["slug"]) is None
    assert tips_content.get_tip(
        db_connection, item["slug"], include_drafts=True
    ) is not None

    tips_content.soft_delete(db_connection, item["id"], None)
    assert tips_content.get_tip(
        db_connection, item["slug"], include_drafts=True
    ) is None
    tips_content.restore(db_connection, item["id"])
    assert tips_content.get_tip(
        db_connection, item["slug"], include_drafts=True
    ) is not None


def test_markdown_is_sanitized_and_code_is_preserved():
    rendered = tips_content.render_markdown(
        "<script>alert(1)</script>\n\n## 자동 목차 제목\n\n```python\nprint('ok')\n```"
    )
    assert "<script" not in rendered
    assert "alert(1)" in rendered
    assert "codehilite" in rendered
    assert "print" in rendered
    assert 'id="' in rendered


def test_dashboard_list_and_detail_routes(monkeypatch, tmp_path):
    db_path = tmp_path / "tips-routes.db"
    attachment_path = tmp_path / "tip-attachments"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    monkeypatch.setattr("config.TIPS_ATTACHMENT_DIR", str(attachment_path))

    import app as app_module
    from dashboard_db import schema

    connection = schema.connect(str(db_path))
    cursor = connection.execute(
        """INSERT INTO dashboard_users
           (username, password_hash, role, is_active, created_at)
           VALUES ('admin', 'unused', 'admin', 1, '2026-07-29T00:00:00')"""
    )
    user_id = cursor.lastrowid
    item = tips_content.save_tip(connection, {
        "title": "라우트 테스트", "body": "안전한 **본문**", "category": "Python",
    }, user_id)
    connection.close()

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        with client.session_transaction() as browser_session:
            browser_session["user_id"] = user_id
            browser_session["username"] = "admin"
            browser_session["role"] = "admin"
            browser_session["csrf_token"] = "c" * 64
        listing = client.get("/resources")
        comment_response = client.post(
            f"/resources/{item['slug']}/comments",
            data={"csrf_token": "c" * 64, "content": "<script>의견</script>"},
        )
        detail = client.get(f"/resources/{item['slug']}")

    assert listing.status_code == 200
    assert "라우트 테스트" in listing.get_data(as_text=True)
    assert comment_response.status_code == 302
    assert detail.status_code == 200
    assert "<strong>본문</strong>" in detail.get_data(as_text=True)
    assert 'id="share-tip-link"' in detail.get_data(as_text=True)
    assert 'id="tip-toc"' in detail.get_data(as_text=True)
    assert 'id="tip-progress-fill"' in detail.get_data(as_text=True)
    assert "&lt;script&gt;의견&lt;/script&gt;" in detail.get_data(as_text=True)
    assert "<script>의견</script>" not in detail.get_data(as_text=True)


def test_new_tip_form_includes_code_block_guide(monkeypatch, tmp_path):
    db_path = tmp_path / "tips-form-guide.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))

    import app as app_module
    from dashboard_db import schema

    connection = schema.connect(str(db_path))
    cursor = connection.execute(
        """INSERT INTO dashboard_users
           (username, password_hash, role, is_active, created_at)
           VALUES ('admin-form', 'unused', 'admin', 1, '2026-07-31T00:00:00')"""
    )
    user_id = cursor.lastrowid
    connection.commit()
    connection.close()

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        with client.session_transaction() as browser_session:
            browser_session["user_id"] = user_id
            browser_session["username"] = "admin-form"
            browser_session["role"] = "admin"
            browser_session["csrf_token"] = "f" * 64
        response = client.get("/resources/new")

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "코드블록 사용 가이드" in html
    assert "```python" in html


def test_related_sites_public_read_and_admin_management(monkeypatch, tmp_path):
    db_path = tmp_path / "related-sites.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))

    import app as app_module
    from dashboard_db import schema

    connection = schema.connect(str(db_path))
    cursor = connection.execute(
        """INSERT INTO dashboard_users
           (username, password_hash, role, is_active, created_at)
           VALUES ('admin', 'unused', 'admin', 1, '2026-07-30T00:00:00')"""
    )
    user_id = cursor.lastrowid
    connection.commit()
    connection.close()

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        public_page = client.get("/resources/sites")
        anonymous_create = client.post(
            "/resources/sites",
            data={
                "title": "허용되지 않는 등록",
                "url": "https://example.invalid",
            },
        )
        with client.session_transaction() as browser_session:
            browser_session["user_id"] = user_id
            browser_session["username"] = "admin"
            browser_session["role"] = "admin"
            browser_session["csrf_token"] = "d" * 64
        category_created = client.post(
            "/resources/sites/categories",
            data={
                "csrf_token": "d" * 64,
                "name": "통계·공공데이터",
            },
        )
        created = client.post(
            "/resources/sites",
            data={
                "csrf_token": "d" * 64,
                "title": "국가법령정보센터",
                "url": "https://www.law.go.kr/",
                "description": "현행 법령 원문 검색",
                "category": "법률·규제",
                "tags": "법령,규제",
                "is_pinned": "1",
                "is_public": "1",
            },
        )
        listing = client.get("/resources/sites?q=법령")

    assert public_page.status_code == 200
    assert "관련 사이트" in public_page.get_data(as_text=True)
    assert anonymous_create.status_code == 403
    assert category_created.status_code == 302
    assert created.status_code == 302
    page = listing.get_data(as_text=True)
    assert listing.status_code == 200
    assert "국가법령정보센터" in page
    assert "https://www.law.go.kr/" in page
    assert "법률·규제" in page

    connection = schema.connect(str(db_path))
    site = connection.execute(
        "SELECT * FROM related_sites WHERE title='국가법령정보센터'"
    ).fetchone()
    assert site["is_pinned"] == 1
    category = connection.execute(
        "SELECT * FROM related_site_categories WHERE name=?",
        ("통계·공공데이터",),
    ).fetchone()
    assert category is not None
    assert category["is_active"] == 1
    connection.close()


def test_related_site_rejects_non_http_url(monkeypatch, tmp_path):
    db_path = tmp_path / "related-sites-invalid.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))

    import app as app_module
    from dashboard_db import schema

    connection = schema.connect(str(db_path))
    cursor = connection.execute(
        """INSERT INTO dashboard_users
           (username, password_hash, role, is_active, created_at)
           VALUES ('admin2', 'unused', 'admin', 1, '2026-07-30T00:00:00')"""
    )
    user_id = cursor.lastrowid
    connection.commit()
    connection.close()

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        with client.session_transaction() as browser_session:
            browser_session["user_id"] = user_id
            browser_session["username"] = "admin2"
            browser_session["role"] = "admin"
            browser_session["csrf_token"] = "e" * 64
        response = client.post(
            "/resources/sites",
            data={
                "csrf_token": "e" * 64,
                "title": "위험한 주소",
                "url": "javascript:alert(1)",
                "is_public": "1",
            },
        )

    assert response.status_code == 302
    connection = schema.connect(str(db_path))
    assert connection.execute("SELECT COUNT(*) FROM related_sites").fetchone()[0] == 0
    connection.close()


def test_comment_update_and_soft_delete(db_connection):
    cursor = db_connection.execute(
        """INSERT INTO dashboard_users
           (username, password_hash, role, is_active, created_at)
           VALUES ('commenter', 'unused', 'user', 1, '2026-07-29T00:00:00')"""
    )
    user_id = cursor.lastrowid
    item = tips_content.save_tip(
        db_connection, {"title": "댓글 자료", "body": "본문"}, user_id
    )
    comment_id = tips_content.add_comment(
        db_connection, item["id"], user_id, "첫 댓글"
    )
    assert tips_content.comments(db_connection, item["id"])[0]["content"] == "첫 댓글"

    tips_content.update_comment(db_connection, comment_id, "수정 댓글")
    assert tips_content.get_comment(db_connection, comment_id)["content"] == "수정 댓글"

    tips_content.delete_comment(db_connection, comment_id, user_id)
    assert tips_content.comments(db_connection, item["id"]) == []
    assert tips_content.get_comment(db_connection, comment_id)["is_deleted"] == 1


def test_portfolio_adapter_accepts_dashboard_tip_without_summary(
    db_connection, monkeypatch
):
    import importlib.util
    from pathlib import Path

    item = tips_content.save_tip(db_connection, {
        "title": "요약 없는 공개 자료",
        "summary": "",
        "body": "본문은 정상적으로 작성되어 있습니다.",
        "category": "기타",
        "published_date": "2026-07-29",
    }, None)
    db_path = db_connection.execute("PRAGMA database_list").fetchone()[2]
    adapter_path = (
        Path(__file__).resolve().parents[1]
        / "deployment"
        / "portfolio_tips_content.py"
    )
    spec = importlib.util.spec_from_file_location(
        "portfolio_tips_content_test", adapter_path
    )
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    monkeypatch.setattr(adapter, "DASHBOARD_TIPS_DB", db_path)

    articles = adapter.load_all_articles()

    assert [article.id for article in articles] == [item["id"]]
    assert articles[0].summary == ""

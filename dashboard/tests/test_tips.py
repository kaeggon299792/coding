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
        "<script>alert(1)</script>\n\n```python\nprint('ok')\n```"
    )
    assert "<script" not in rendered
    assert "alert(1)" in rendered
    assert "codehilite" in rendered
    assert "print" in rendered


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
        listing = client.get("/tips")
        comment_response = client.post(
            f"/tips/{item['slug']}/comments",
            data={"csrf_token": "c" * 64, "content": "<script>의견</script>"},
        )
        detail = client.get(f"/tips/{item['slug']}")

    assert listing.status_code == 200
    assert "라우트 테스트" in listing.get_data(as_text=True)
    assert comment_response.status_code == 302
    assert detail.status_code == 200
    assert "<strong>본문</strong>" in detail.get_data(as_text=True)
    assert 'id="share-tip-link"' in detail.get_data(as_text=True)
    assert "&lt;script&gt;의견&lt;/script&gt;" in detail.get_data(as_text=True)
    assert "<script>의견</script>" not in detail.get_data(as_text=True)


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

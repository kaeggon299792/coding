def _create_user(connection, username, role):
    cursor = connection.execute(
        """INSERT INTO dashboard_users
           (username, password_hash, role, is_active, created_at)
           VALUES (?, 'unused', ?, 1, '2026-08-04T00:00:00')""",
        (username, role),
    )
    connection.commit()
    return cursor.lastrowid


def _login(client, user_id, username, role, token):
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = user_id
        browser_session["username"] = username
        browser_session["role"] = role
        browser_session["csrf_token"] = token


def test_admin_manages_tip_categories_and_renames_existing_articles(monkeypatch, tmp_path):
    db_path = tmp_path / "tips-categories.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))

    import app as app_module
    from dashboard_db import schema
    from services import tips_content

    connection = schema.connect(str(db_path))
    regular_id = _create_user(connection, "category-user", "user")
    admin_id = _create_user(connection, "category-admin", "admin")
    article = tips_content.save_tip(connection, {
        "title": "기존 엑셀 자료", "slug": "existing-excel-tip", "summary": "",
        "body": "본문", "category": "Excel", "tags": "",
        "published_date": "2026-08-04", "featured": False, "draft": False,
        "cover_image": "",
    }, admin_id)
    excel_id = connection.execute(
        "SELECT id FROM tips_categories WHERE name='Excel'"
    ).fetchone()["id"]
    connection.close()

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        assert client.get("/tips/categories").status_code == 302
        _login(client, regular_id, "category-user", "user", "u" * 64)
        assert client.get("/tips/categories").status_code == 403
        assert client.post(
            f"/tips/categories/{excel_id}/rename",
            data={"csrf_token": "u" * 64, "name": "스프레드시트"},
        ).status_code == 403

        _login(client, admin_id, "category-admin", "admin", "a" * 64)
        page = client.get("/tips/categories")
        assert page.status_code == 200
        assert "자료실 카테고리 관리" in page.get_data(as_text=True)
        assert "기존 엑셀 자료" not in page.get_data(as_text=True)

        created = client.post(
            "/tips/categories",
            data={"csrf_token": "a" * 64, "name": "카지노 운영"},
            follow_redirects=True,
        )
        assert created.status_code == 200
        assert "카지노 운영" in created.get_data(as_text=True)
        duplicate = client.post(
            "/tips/categories",
            data={"csrf_token": "a" * 64, "name": "카지노 운영"},
            follow_redirects=True,
        )
        assert "이미 등록된 카테고리" in duplicate.get_data(as_text=True)

        renamed = client.post(
            f"/tips/categories/{excel_id}/rename",
            data={"csrf_token": "a" * 64, "name": "스프레드시트"},
            follow_redirects=True,
        )
        assert "기존 자료를 함께 변경" in renamed.get_data(as_text=True)
        assert "스프레드시트" in client.get("/tips/new").get_data(as_text=True)

        toggled = client.post(
            f"/tips/categories/{excel_id}/toggle",
            data={"csrf_token": "a" * 64},
            follow_redirects=True,
        )
        assert "새 글 선택 목록에서 숨겼습니다" in toggled.get_data(as_text=True)
        assert "스프레드시트" not in client.get("/tips/new").get_data(as_text=True)
        forged = client.post(
            "/tips/new",
            data={
                "csrf_token": "a" * 64, "title": "숨김 카테고리 글",
                "slug": "hidden-category-tip", "body": "본문",
                "category": "스프레드시트", "published_date": "2026-08-04",
            },
        )
        assert forged.status_code == 400
        assert "현재 사용할 수 없는 카테고리" in forged.get_data(as_text=True)

    connection = schema.connect(str(db_path))
    assert connection.execute(
        "SELECT category FROM tips_articles WHERE id=?", (article["id"],)
    ).fetchone()["category"] == "스프레드시트"
    assert connection.execute(
        "SELECT is_active FROM tips_categories WHERE id=?", (excel_id,)
    ).fetchone()["is_active"] == 0
    connection.close()

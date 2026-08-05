import pytest


@pytest.fixture
def credits_client(monkeypatch, tmp_path):
    import app as app_module
    import config
    from dashboard_db import schema

    db_path = tmp_path / "credits.db"
    monkeypatch.setattr(config, "DASHBOARD_DB_FILE", str(db_path))
    app_module.app.config.update(TESTING=True)
    connection = schema.connect(str(db_path))
    cursor = connection.execute(
        """INSERT INTO dashboard_users
           (username, password_hash, role, membership_level, is_active,
            approval_status, created_at)
           VALUES ('credits-admin', 'unused', 'admin', 'black', 1,
                   'approved', '2026-08-06T00:00:00')"""
    )
    connection.commit()
    admin_id = cursor.lastrowid
    connection.close()
    return app_module.app.test_client(), db_path, admin_id


def _login_admin(client, admin_id):
    with client.session_transaction() as session:
        session["user_id"] = admin_id
        session["username"] = "credits-admin"
        session["role"] = "admin"
        session["csrf_token"] = "c" * 64


def test_credits_page_uses_seeded_database_rows(credits_client):
    client, _, _ = credits_client
    response = client.get("/credits")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "출처 및 저작권" in html
    assert "카지노 관련 뉴스" in html
    assert "18건" in html
    assert client.get("/admin/credits").status_code == 302


def test_admin_can_create_edit_and_hide_credit_source(credits_client):
    client, db_path, admin_id = credits_client
    _login_admin(client, admin_id)
    admin_page = client.get("/admin/credits")
    assert admin_page.status_code == 200
    assert "등록된 출처" in admin_page.get_data(as_text=True)

    created = client.post(
        "/admin/credits",
        data={
            "csrf_token": "c" * 64,
            "menu": "테스트 메뉴",
            "dataset": "테스트 데이터",
            "source_name": "테스트 기관",
            "source_url": "https://example.com/source",
            "cadence": "월 1회",
            "freshness_key": "",
            "sort_order": "190",
        },
    )
    assert created.status_code == 302
    public_html = client.get("/credits").get_data(as_text=True)
    assert "테스트 데이터" in public_html

    from dashboard_db import schema

    connection = schema.connect(str(db_path))
    row = connection.execute(
        "SELECT id FROM credit_sources WHERE dataset=?", ("테스트 데이터",)
    ).fetchone()
    connection.close()
    source_id = row["id"]
    edited = client.post(
        f"/admin/credits/{source_id}/edit",
        data={
            "csrf_token": "c" * 64,
            "menu": "테스트 메뉴",
            "dataset": "수정된 데이터",
            "source_name": "테스트 기관",
            "source_url": "https://example.com/source",
            "cadence": "주 1회",
            "freshness_key": "",
            "sort_order": "190",
            "is_active": "1",
        },
    )
    assert edited.status_code == 302
    assert "수정된 데이터" in client.get("/credits").get_data(as_text=True)
    hidden = client.post(
        f"/admin/credits/{source_id}/hide", data={"csrf_token": "c" * 64}
    )
    assert hidden.status_code == 302
    assert "수정된 데이터" not in client.get("/credits").get_data(as_text=True)


def test_credit_source_rejects_unsafe_url(credits_client):
    client, db_path, admin_id = credits_client
    _login_admin(client, admin_id)
    response = client.post(
        "/admin/credits",
        data={
            "csrf_token": "c" * 64,
            "menu": "테스트",
            "dataset": "안전성 테스트",
            "source_name": "테스트",
            "source_url": "javascript:alert(1)",
            "cadence": "수동",
            "freshness_key": "",
            "sort_order": "100",
        },
    )
    assert response.status_code == 302
    from dashboard_db import schema

    connection = schema.connect(str(db_path))
    count = connection.execute(
        "SELECT COUNT(*) FROM credit_sources WHERE dataset=?", ("안전성 테스트",)
    ).fetchone()[0]
    connection.close()
    assert count == 0

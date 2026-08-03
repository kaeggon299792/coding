import hashlib
import re
import sqlite3
from http.cookies import SimpleCookie

import pytest
from werkzeug.security import generate_password_hash


@pytest.fixture
def account_client(monkeypatch, tmp_path):
    db_path = tmp_path / "account_test.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))

    import app as app_module
    from dashboard_db import queries
    from extensions import dashboard_db

    connection = dashboard_db()
    queries.create_user(
        connection, "admin", generate_password_hash("admin-password-123!")
    )
    connection.execute("UPDATE dashboard_users SET role='admin' WHERE username='admin'")
    queries.create_user(
        connection, "employee", generate_password_hash("employee-password-123")
    )
    connection.execute(
        "UPDATE dashboard_users SET email='before@example.com' WHERE username='employee'"
    )
    connection.commit()
    connection.close()

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        yield client, db_path


def _csrf(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([a-f0-9]+)"', html).group(1)


def _login(client, remember=False):
    response = client.post(
        "/login",
        data={
            "username": "employee",
            "password": "employee-password-123",
            "csrf_token": _csrf(client),
            "remember_me": "1" if remember else "0",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    return response


def test_remember_login_stores_only_hash(account_client):
    client, db_path = account_client
    response = _login(client, remember=True)
    cookie = SimpleCookie()
    cookie.load(response.headers["Set-Cookie"])
    value = cookie["casino_in_remember"].value
    selector, raw_token = value.split(".", 1)

    connection = sqlite3.connect(db_path)
    row = connection.execute(
        "SELECT token_hash FROM remember_login_tokens WHERE selector=?", (selector,)
    ).fetchone()
    connection.close()
    assert row is not None
    assert row[0] != raw_token
    assert row[0] == hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert "Secure" in response.headers["Set-Cookie"]
    assert "SameSite=Lax" in response.headers["Set-Cookie"]


def test_remember_login_rotates_after_successful_restore(account_client):
    client, db_path = account_client
    response = _login(client, remember=True)
    original = SimpleCookie()
    original.load(response.headers["Set-Cookie"])
    original_value = original["casino_in_remember"].value
    original_selector = original_value.split(".", 1)[0]
    with client.session_transaction() as flask_session:
        flask_session.clear()

    restored = client.get("/", follow_redirects=False)
    rotated = SimpleCookie()
    rotated.load(restored.headers["Set-Cookie"])
    rotated_value = rotated["casino_in_remember"].value
    assert rotated_value != original_value

    connection = sqlite3.connect(db_path)
    old_revoked = connection.execute(
        "SELECT revoked_at FROM remember_login_tokens WHERE selector=?",
        (original_selector,),
    ).fetchone()[0]
    active = connection.execute(
        "SELECT COUNT(*) FROM remember_login_tokens WHERE revoked_at IS NULL"
    ).fetchone()[0]
    connection.close()
    assert old_revoked
    assert active == 1


def test_email_change_requires_current_password(account_client):
    client, db_path = account_client
    _login(client)
    csrf = _csrf(client, "/account")
    rejected = client.post(
        "/account/email",
        data={"csrf_token": csrf, "email": "after@example.com", "current_password": "wrong"},
        follow_redirects=False,
    )
    assert rejected.status_code == 302
    assert "error=" in rejected.headers["Location"]

    accepted = client.post(
        "/account/email",
        data={
            "csrf_token": csrf,
            "email": "after@example.com",
            "current_password": "employee-password-123",
        },
        follow_redirects=False,
    )
    assert accepted.status_code == 302
    connection = sqlite3.connect(db_path)
    email = connection.execute(
        "SELECT email FROM dashboard_users WHERE username='employee'"
    ).fetchone()[0]
    connection.close()
    assert email == "after@example.com"


def test_password_change_revokes_remember_login(account_client):
    client, db_path = account_client
    _login(client, remember=True)
    csrf = _csrf(client, "/account")
    response = client.post(
        "/account/password",
        data={
            "csrf_token": csrf,
            "current_password": "employee-password-123",
            "new_password": "New-password-123!",
            "new_password_confirmation": "New-password-123!",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "password_changed=1" in response.headers["Location"]
    with client.session_transaction() as flask_session:
        assert "user_id" not in flask_session
    connection = sqlite3.connect(db_path)
    revoked_at = connection.execute(
        "SELECT revoked_at FROM remember_login_tokens"
    ).fetchone()[0]
    connection.close()
    assert revoked_at


def test_admin_page_renders_separately_with_font_selector(account_client):
    client, _ = account_client
    response = client.post(
        "/login",
        data={
            "username": "admin",
            "password": "admin-password-123!",
            "csrf_token": _csrf(client),
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    page = client.get("/admin/users")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "관리자 페이지" in html
    assert "기본 웹폰트" in html
    assert "프리텐다드" in html
    assert "고운바탕" in html
    assert "함렛" in html

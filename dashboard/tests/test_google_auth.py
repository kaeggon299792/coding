import sqlite3

import pytest
from flask import redirect
from werkzeug.security import generate_password_hash


@pytest.fixture
def google_client(monkeypatch, tmp_path):
    db_path = tmp_path / "google_auth.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    monkeypatch.setattr("config.GOOGLE_CLIENT_ID", "test-google-client-id")
    monkeypatch.setattr("config.GOOGLE_CLIENT_SECRET", "test-google-client-secret")
    monkeypatch.setattr(
        "config.GOOGLE_REDIRECT_URI",
        "https://casino.shingoon.me/auth/google/callback",
    )

    import app as app_module
    import auth

    monkeypatch.setattr(
        auth.telegram_alert, "send_alert", lambda message, force=False: True
    )

    app_module.app.config.update(TESTING=True, SERVER_NAME=None)
    with app_module.app.test_client() as client:
        yield client, auth, db_path


def _userinfo(**overrides):
    data = {
        "sub": "google-sub-123",
        "email": "google.user@example.com",
        "email_verified": True,
        "name": "Google User",
        "picture": "https://lh3.googleusercontent.com/example/photo.jpg",
    }
    data.update(overrides)
    return data


def _mock_callback(monkeypatch, auth_module, userinfo):
    monkeypatch.setattr(
        auth_module.oauth.google,
        "authorize_access_token",
        lambda: {"userinfo": userinfo, "access_token": "test-token-not-persisted"},
    )


def test_protected_page_redirects_to_existing_login_with_next(google_client):
    client, _, _ = google_client
    response = client.get("/official-docs/?q=casino", follow_redirects=False)
    assert response.status_code == 302
    assert "/login?next=" in response.headers["Location"]
    assert "q%3Dcasino" in response.headers["Location"]


def test_google_login_redirects_to_provider(google_client, monkeypatch):
    client, auth_module, _ = google_client
    monkeypatch.setattr(
        auth_module.oauth.google,
        "authorize_redirect",
        lambda redirect_uri: redirect(
            "https://accounts.google.com/o/oauth2/v2/auth?state=mock-state"
        ),
    )
    response = client.get("/login/google", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].startswith("https://accounts.google.com/")


def test_google_callback_creates_pending_user_without_starting_session(
    google_client, monkeypatch
):
    client, auth_module, db_path = google_client
    alerts = []
    monkeypatch.setattr(
        auth_module.telegram_alert, "send_alert", lambda message, force=False: alerts.append(message) or True
    )
    _mock_callback(monkeypatch, auth_module, _userinfo())

    response = client.get("/auth/google/callback", follow_redirects=False)
    assert response.status_code == 403
    with client.session_transaction() as flask_session:
        assert "user_id" not in flask_session
        assert "access_token" not in flask_session
        assert "id_token" not in flask_session

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    row = connection.execute(
        "SELECT * FROM dashboard_users WHERE google_sub=?", ("google-sub-123",)
    ).fetchone()
    connection.close()
    assert row["google_sub"] == "google-sub-123"
    assert row["email"] == "google.user@example.com"
    assert row["is_active"] == 0
    assert row["approval_status"] == "pending"
    assert row["last_login_at"] is None
    assert len(alerts) == 1
    assert "Google" in alerts[0]
    assert f"pending_user={row['id']}" in alerts[0]


def test_google_callback_rejects_unverified_email(google_client, monkeypatch):
    client, auth_module, _ = google_client
    _mock_callback(monkeypatch, auth_module, _userinfo(email_verified=False))
    response = client.get("/auth/google/callback")
    assert response.status_code == 403
    assert "이메일 인증" in response.get_data(as_text=True)


def test_google_callback_rejects_missing_sub(google_client, monkeypatch):
    client, auth_module, _ = google_client
    _mock_callback(monkeypatch, auth_module, _userinfo(sub=""))
    response = client.get("/auth/google/callback")
    assert response.status_code == 400
    assert "계정 식별 정보" in response.get_data(as_text=True)


def test_existing_verified_email_is_linked_without_duplicate(
    google_client, monkeypatch
):
    client, auth_module, db_path = google_client
    from dashboard_db import schema

    connection = schema.connect(str(db_path))
    cursor = connection.execute(
        """
        INSERT INTO dashboard_users
            (username, password_hash, created_at, role, is_active, email,
             approval_status)
        VALUES (?, ?, ?, 'user', 1, ?, 'approved')
        """,
        (
            "existing-user",
            generate_password_hash("existing-password", method="scrypt"),
            "2026-08-01T00:00:00+09:00",
            "google.user@example.com",
        ),
    )
    existing_id = cursor.lastrowid
    connection.commit()
    connection.close()

    _mock_callback(monkeypatch, auth_module, _userinfo())
    response = client.get("/auth/google/callback")
    assert response.status_code == 302

    connection = sqlite3.connect(db_path)
    count = connection.execute("SELECT COUNT(*) FROM dashboard_users").fetchone()[0]
    linked = connection.execute(
        "SELECT id, google_sub FROM dashboard_users WHERE id=?", (existing_id,)
    ).fetchone()
    connection.close()
    assert count == 1
    assert linked == (existing_id, "google-sub-123")


def test_existing_google_sub_does_not_create_duplicate(google_client, monkeypatch):
    client, auth_module, db_path = google_client
    from dashboard_db import schema

    connection = schema.connect(str(db_path))
    connection.execute(
        """
        INSERT INTO dashboard_users
            (username, password_hash, created_at, role, is_active, email,
             approval_status, google_sub)
        VALUES (?, ?, ?, 'user', 1, ?, 'approved', ?)
        """,
        (
            "existing-google-user",
            generate_password_hash("existing-password", method="scrypt"),
            "2026-08-01T00:00:00+09:00",
            "google.user@example.com",
            "google-sub-123",
        ),
    )
    connection.commit()
    connection.close()

    _mock_callback(monkeypatch, auth_module, _userinfo())
    assert client.get("/auth/google/callback").status_code == 302
    with client.session_transaction() as flask_session:
        flask_session.clear()
    assert client.get("/auth/google/callback").status_code == 302

    connection = sqlite3.connect(db_path)
    count = connection.execute("SELECT COUNT(*) FROM dashboard_users").fetchone()[0]
    connection.close()
    assert count == 1


def test_existing_pending_google_account_cannot_login_or_repeat_alert(
    google_client, monkeypatch
):
    client, auth_module, db_path = google_client
    alerts = []
    monkeypatch.setattr(
        auth_module.telegram_alert, "send_alert", lambda message, force=False: alerts.append(message) or True
    )
    _mock_callback(monkeypatch, auth_module, _userinfo())
    assert client.get("/auth/google/callback").status_code == 403
    assert len(alerts) == 1

    assert client.get("/auth/google/callback").status_code == 403
    assert len(alerts) == 1
    with client.session_transaction() as flask_session:
        assert "user_id" not in flask_session

    connection = sqlite3.connect(db_path)
    count = connection.execute("SELECT COUNT(*) FROM dashboard_users").fetchone()[0]
    connection.close()
    assert count == 1


def test_logout_clears_google_session(google_client, monkeypatch):
    client, auth_module, _ = google_client
    _mock_callback(monkeypatch, auth_module, _userinfo())
    client.get("/auth/google/callback")
    with client.session_transaction() as flask_session:
        flask_session["csrf_token"] = "known-csrf-token"
    response = client.post(
        "/logout", data={"csrf_token": "known-csrf-token"}, follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    with client.session_transaction() as flask_session:
        assert "user_id" not in flask_session


def test_google_callback_rejects_external_next_url(google_client, monkeypatch):
    client, auth_module, db_path = google_client
    from dashboard_db import schema

    connection = schema.connect(str(db_path))
    connection.execute(
        """
        INSERT INTO dashboard_users
            (username, password_hash, created_at, role, is_active, email,
             approval_status, google_sub)
        VALUES (?, ?, ?, 'user', 1, ?, 'approved', ?)
        """,
        (
            "approved-google-user",
            generate_password_hash("existing-password", method="scrypt"),
            "2026-08-01T00:00:00+09:00",
            "google.user@example.com",
            "google-sub-123",
        ),
    )
    connection.commit()
    connection.close()
    _mock_callback(monkeypatch, auth_module, _userinfo())
    with client.session_transaction() as flask_session:
        flask_session["oauth_next"] = "https://evil.example/steal"
    response = client.get("/auth/google/callback", follow_redirects=False)
    assert response.status_code == 302
    assert "evil.example" not in response.headers["Location"]


def test_google_login_reports_missing_environment(google_client, monkeypatch):
    client, _, _ = google_client
    monkeypatch.setattr("config.GOOGLE_CLIENT_SECRET", "")
    response = client.get("/login/google")
    assert response.status_code == 503
    assert "관리자에게 문의" in response.get_data(as_text=True)


def test_google_login_page_has_google_button(google_client):
    client, _, _ = google_client
    response = client.get("/login")
    html = response.get_data(as_text=True)
    assert "Google 계정으로 로그인" in html
    assert 'href="/login/google"' in html
    assert "google-g.svg" in html

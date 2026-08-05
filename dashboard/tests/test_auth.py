import re

import pytest
from werkzeug.security import generate_password_hash


@pytest.fixture
def client(monkeypatch, tmp_path):
    db_path = tmp_path / "auth_test.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))

    import app as app_module
    from dashboard_db import queries
    from extensions import dashboard_db

    conn = dashboard_db()
    queries.create_user(conn, "admin", generate_password_hash("correct-horse-battery-staple"))
    conn.close()

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def _get_csrf(client, path):
    response = client.get(path)
    match = re.search(r'name="csrf_token" value="([a-f0-9]+)"', response.get_data(as_text=True))
    return match.group(1)


def test_login_requires_csrf_token(client):
    response = client.post("/login", data={"username": "admin", "password": "correct-horse-battery-staple"})
    assert response.status_code == 400


def test_login_rejects_wrong_password(client):
    csrf = _get_csrf(client, "/login")
    response = client.post(
        "/login", data={"username": "admin", "password": "wrong-password", "csrf_token": csrf}
    )
    assert response.status_code == 401


def test_login_succeeds_with_correct_credentials(client):
    csrf = _get_csrf(client, "/login")
    response = client.post(
        "/login",
        data={"username": "admin", "password": "correct-horse-battery-staple", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_protected_page_redirects_to_login_when_not_authenticated(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "CASINO IN" in page
    assert "/login" in page


def test_api_settings_redirects_anonymous_user_to_login(client):
    response = client.get("/admin/ai-settings", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_full_login_then_access_dashboard(client):
    csrf = _get_csrf(client, "/login")
    client.post(
        "/login",
        data={"username": "admin", "password": "correct-horse-battery-staple", "csrf_token": csrf},
    )
    response = client.get("/")
    assert response.status_code == 200


def test_admin_can_immediately_anonymize_another_account(client):
    from dashboard_db import queries
    from extensions import dashboard_db

    connection = dashboard_db()
    connection.execute(
        "UPDATE dashboard_users SET role='admin', approval_status='approved' WHERE username='admin'"
    )
    target_id = queries.create_user(
        connection, "delete-now-user", generate_password_hash("temporary-password")
    )
    connection.execute(
        """
        UPDATE dashboard_users
        SET email='delete@example.com', name='Delete Me', approval_status='approved'
        WHERE id=?
        """,
        (target_id,),
    )
    connection.commit()
    connection.close()
    csrf = _get_csrf(client, "/login")
    client.post(
        "/login",
        data={
            "username": "admin",
            "password": "correct-horse-battery-staple",
            "csrf_token": csrf,
        },
    )
    csrf = _get_csrf(client, "/admin/users")
    assert client.post(
        f"/admin/users/{target_id}/delete-now",
        data={"csrf_token": "invalid", "confirmation": "delete-now-user"},
    ).status_code == 400
    assert client.post(
        "/admin/users/1/delete-now",
        data={"csrf_token": csrf, "confirmation": "admin"},
    ).status_code == 302
    response = client.post(
        f"/admin/users/{target_id}/delete-now",
        data={"csrf_token": csrf, "confirmation": "delete-now-user"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    connection = dashboard_db()
    target = connection.execute(
        "SELECT * FROM dashboard_users WHERE id=?", (target_id,)
    ).fetchone()
    audit = connection.execute(
        "SELECT action FROM dashboard_user_audit WHERE target_user_id=? ORDER BY id DESC",
        (target_id,),
    ).fetchone()
    connection.close()
    assert target["username"] == f"deleted-user-{target_id}"
    assert target["approval_status"] == "deleted"
    assert target["email"] is None
    assert target["name"] is None
    assert audit["action"] == "ACCOUNT_DELETION_IMMEDIATE"


def test_registration_sends_secure_admin_review_link(client, monkeypatch):
    from extensions import dashboard_db

    connection = dashboard_db()
    connection.execute(
        """INSERT INTO site_settings(setting_key,setting_value,updated_at)
           VALUES ('registration_auto_approval','0','2026-08-05T00:00:00+09:00')"""
    )
    connection.commit()
    connection.close()
    sent = []
    monkeypatch.setattr(
        "auth.telegram_alert.send_alert",
        lambda message, *, force=False: sent.append((message, force)) or True,
    )
    csrf = _get_csrf(client, "/register")
    response = client.post(
        "/register",
        data={
            "username": "pending.user",
            "email": "pending@example.com",
            "password": "Strong-password-123!",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert len(sent) == 1
    message, force = sent[0]
    assert force is True
    assert "pending.user" in message
    assert "pending@example.com" in message
    assert "https://www.casinoin.kr/admin/users?pending_user=2#user-2" in message
    assert "Strong-password" not in message

    review = client.get("/admin/users?pending_user=2", follow_redirects=False)
    assert review.status_code == 302
    assert "/login" in review.headers["Location"]
    approval_attempt = client.post(
        "/admin/users/2/toggle", data={}, follow_redirects=False
    )
    assert approval_attempt.status_code == 302
    assert "/login" in approval_attempt.headers["Location"]

    connection = dashboard_db()
    pending = connection.execute(
        "SELECT is_active, approval_status FROM dashboard_users WHERE id=2"
    ).fetchone()
    connection.close()
    assert pending["is_active"] == 0
    assert pending["approval_status"] == "pending"


def test_registration_defaults_to_auto_approval(client, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "auth.telegram_alert.send_alert",
        lambda message, *, force=False: sent.append((message, force)) or True,
    )
    csrf = _get_csrf(client, "/register")
    response = client.post(
        "/register",
        data={
            "username": "auto.user",
            "email": "auto@example.com",
            "password": "Strong-password-123!",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "registered=approved" in response.headers["Location"]

    from extensions import dashboard_db

    connection = dashboard_db()
    user = connection.execute(
        "SELECT is_active,approval_status FROM dashboard_users WHERE username='auto.user'"
    ).fetchone()
    connection.close()
    assert (user["is_active"], user["approval_status"]) == (1, "approved")
    assert len(sent) == 1
    assert "자동 승인 완료" in sent[0][0]
    assert "Strong-password" not in sent[0][0]


def test_admin_can_change_registration_approval_policy(client):
    from extensions import dashboard_db

    connection = dashboard_db()
    connection.execute(
        "UPDATE dashboard_users SET role='admin',is_active=1,approval_status='approved' WHERE username='admin'"
    )
    connection.commit()
    connection.close()
    csrf = _get_csrf(client, "/login")
    client.post(
        "/login",
        data={
            "username": "admin",
            "password": "correct-horse-battery-staple",
            "csrf_token": csrf,
        },
    )
    csrf = _get_csrf(client, "/admin/users")
    assert client.post(
        "/admin/site-settings/registration-approval",
        data={"csrf_token": "wrong", "approval_mode": "manual"},
    ).status_code == 400
    response = client.post(
        "/admin/site-settings/registration-approval",
        data={"csrf_token": csrf, "approval_mode": "manual"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    connection = dashboard_db()
    setting = connection.execute(
        "SELECT setting_value FROM site_settings WHERE setting_key='registration_auto_approval'"
    ).fetchone()["setting_value"]
    audit = connection.execute(
        "SELECT action FROM security_audit_log WHERE action='REGISTRATION_APPROVAL_POLICY_UPDATED'"
    ).fetchone()
    connection.close()
    assert setting == "0"
    assert audit["action"] == "REGISTRATION_APPROVAL_POLICY_UPDATED"


def test_admin_can_change_ai_settings_by_purpose(client):
    from extensions import dashboard_db

    connection = dashboard_db()
    connection.execute(
        "UPDATE dashboard_users SET role='admin',is_active=1,approval_status='approved' WHERE username='admin'"
    )
    connection.commit()
    connection.close()
    csrf = _get_csrf(client, "/login")
    client.post(
        "/login",
        data={
            "username": "admin",
            "password": "correct-horse-battery-staple",
            "csrf_token": csrf,
        },
    )
    account_page = client.get("/admin/users")
    assert account_page.status_code == 200
    assert "용도별 AI 설정" not in account_page.get_data(as_text=True)
    page = client.get("/admin/ai-settings")
    assert page.status_code == 200
    assert "OpenAI 호출 한도" in page.get_data(as_text=True)
    assert "용도별 AI 설정" in page.get_data(as_text=True)
    assert "Gemini 기사 분석 사용량·비용" in page.get_data(as_text=True)
    csrf = _get_csrf(client, "/admin/ai-settings")
    payload = {"csrf_token": csrf}
    purposes = {
        "translation": "gpt-translation-test",
        "news_importance": "gpt-news-test",
        "disclosure_ir": "gpt-disclosure-test",
        "research": "gpt-research-test",
        "legal": "gpt-legal-test",
        "executive": "gpt-executive-test",
    }
    for purpose, model in purposes.items():
        payload[f"{purpose}_enabled"] = "1"
        payload[f"{purpose}_model"] = model
        payload[f"{purpose}_daily_call_limit"] = "25"
    payload["news_importance_importance_threshold"] = "64"
    payload["news_importance_web_importance_threshold"] = "80"

    invalid = dict(payload, csrf_token="invalid")
    assert client.post("/admin/ai-settings/purposes", data=invalid).status_code == 400
    response = client.post(
        "/admin/ai-settings/purposes", data=payload, follow_redirects=False
    )
    assert response.status_code == 302
    assert "/admin/ai-settings?success=" in response.headers["Location"]
    connection = dashboard_db()
    settings = dict(connection.execute(
        "SELECT setting_key,setting_value FROM site_settings WHERE setting_key LIKE 'ai_purpose_%'"
    ).fetchall())
    audit = connection.execute(
        "SELECT action FROM security_audit_log WHERE action='AI_PURPOSE_SETTINGS_UPDATED'"
    ).fetchone()
    connection.close()
    assert settings["ai_purpose_news_importance_model"] == "gpt-news-test"
    assert settings["ai_purpose_news_importance_daily_call_limit"] == "25"
    assert settings["ai_purpose_news_importance_importance_threshold"] == "64"
    assert settings["ai_purpose_news_importance_web_importance_threshold"] == "80"
    assert audit["action"] == "AI_PURPOSE_SETTINGS_UPDATED"

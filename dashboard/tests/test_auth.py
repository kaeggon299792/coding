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


def test_public_home_is_available_when_not_authenticated(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 200


def test_protected_page_redirects_to_login_when_not_authenticated(client):
    response = client.get("/official-docs/", follow_redirects=False)
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


def test_logged_in_user_can_access_market_data_page(client):
    csrf = _get_csrf(client, "/login")
    client.post(
        "/login",
        data={
            "username": "admin",
            "password": "correct-horse-battery-staple",
            "csrf_token": csrf,
        },
    )
    response = client.get("/performance/markets")
    assert response.status_code == 200
    assert "주가 정보" in response.get_data(as_text=True)

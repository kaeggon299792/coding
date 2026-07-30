import re

import pytest
from werkzeug.security import generate_password_hash


@pytest.fixture
def client(monkeypatch, tmp_path):
    db_path = tmp_path / "auth_test.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    monkeypatch.setattr(
        "services.market_data.fetch_global_quotes",
        lambda: {"quotes": [], "errors": []},
    )

    import app as app_module
    from dashboard_db import queries
    from extensions import dashboard_db

    conn = dashboard_db()
    queries.create_user(conn, "admin", generate_password_hash("correct-horse-battery-staple"))
    queries.create_user(conn, "employee", generate_password_hash("employee-password-123"))
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
    html = response.get_data(as_text=True)
    assert "업무에 필요한 정보를" in html
    assert "오늘의 주요 현황" in html
    assert "공문 DB 최종 업데이트" not in html
    assert "질문·버그 제보·기능 제안" in html
    assert "CASINO IN / MANAGEMENT DASHBOARD" in html
    assert 'img/casino-in-logo.png' in html
    assert "파라디안 전용" in html
    assert "GTM-MVWKPPRP" in html
    assert "https://www.googletagmanager.com/gtm.js" in html
    policy = response.headers["Content-Security-Policy"]
    assert "script-src 'self' 'nonce-" in policy
    assert "https://www.googletagmanager.com" in policy
    assert "https://www.google-analytics.com" in policy
    assert "frame-src https://www.googletagmanager.com" in policy


def test_login_page_has_guest_access_button(client):
    response = client.get("/login")
    html = response.get_data(as_text=True)
    assert "로그인하지 않고 이용하기" in html
    assert 'href="/"' in html
    assert "CASINO IN / MANAGEMENT DASHBOARD" in html
    assert 'alt="CASINO IN"' in html


def test_legacy_dashboard_redirects_to_unified_home(client):
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_protected_page_redirects_to_login_when_not_authenticated(client):
    response = client.get("/official-docs/", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


@pytest.mark.parametrize(
    "path",
    (
        "/performance/markets",
        "/performance/news",
        "/performance/tourism",
        "/performance/economy",
        "/performance/holidays",
        "/disclosures",
        "/laws",
        "/companies",
        "/library",
        "/search",
        "/tips",
        "/bug-reports",
    ),
)
def test_public_read_pages_do_not_require_login(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 200


def test_paradian_portal_requires_login(client):
    response = client.get("/paradian", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_logged_in_employee_can_access_official_docs_but_not_performance(client):
    csrf = _get_csrf(client, "/login")
    client.post(
        "/login",
        data={
            "username": "employee",
            "password": "employee-password-123",
            "csrf_token": csrf,
        },
    )
    assert client.get("/official-docs/").status_code == 200
    assert client.get("/performance").status_code == 403


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


def test_logged_in_user_can_access_related_news_page(client):
    csrf = _get_csrf(client, "/login")
    client.post(
        "/login",
        data={
            "username": "admin",
            "password": "correct-horse-battery-staple",
            "csrf_token": csrf,
        },
    )
    response = client.get("/performance/news")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "관련 뉴스" in html
    assert "경영진 관점 분석" in html

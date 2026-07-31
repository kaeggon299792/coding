import re
from datetime import datetime, timedelta

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
    assert 'class="public-hero-art-image"' in html
    assert "DATA" not in html
    assert "오늘의 주요 현황" not in html
    assert "공문 DB 자동 갱신" not in html
    assert "질문·버그 제보·기능 제안" in html
    assert "CASINO IN / MANAGEMENT DASHBOARD" not in html
    assert 'img/casino-in-logo.png' in html
    assert "파라디안 전용" in html
    assert "GTM-MVWKPPRP" in html
    assert "https://www.googletagmanager.com/gtm.js" in html
    policy = response.headers["Content-Security-Policy"]
    assert "script-src 'self' 'nonce-" in policy
    assert "https://www.googletagmanager.com" in policy
    assert "https://www.google-analytics.com" in policy
    assert "frame-src https://www.googletagmanager.com" in policy
    assert 'data-casino-wave' in html
    assert re.search(r'<script nonce="[^"]+" src="/static/vendor/three/three\.r149\.min\.js">', html)
    assert re.search(r'<script nonce="[^"]+" src="/static/js/casino-wave-webgl-v2\.js\?v=20260731-lightmotion1">', html)


def test_login_page_has_guest_access_button(client):
    response = client.get("/login")
    html = response.get_data(as_text=True)
    assert "로그인하지 않고 이용하기" in html
    assert 'href="/"' in html
    assert "CASINO IN / MANAGEMENT DASHBOARD" in html
    assert 'alt="CASINO IN"' in html
    assert "내부 업무용 시스템입니다" not in html


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


@pytest.mark.parametrize(
    "path",
    (
        "/performance/tourism",
        "/performance/casino-industry",
        "/performance/casino-industry/visitors",
        "/performance/casino-industry/revenue",
        "/performance/casino-industry/fund",
        "/performance/markets",
        "/performance/news",
        "/performance/economy",
        "/performance/holidays",
        "/performance/salaries",
        "/performance/recruitment",
        "/bug-reports",
        "/credits",
        "/sitemap",
    ),
)
def test_data_and_feedback_pages_render_one_centralized_footer(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert html.count('class="legal-footer"') == 1
    assert 'class="site-footer"' not in html
    assert 'href="https://shingoon.me/"' in html
    assert 'rel="noopener noreferrer"' in html


def test_sitemap_renders_data_and_library_submenus(client):
    response = client.get("/sitemap")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'class="sitemap-children' in html
    assert "연도별 카지노 이용객" in html
    assert "기금 부과 현황" in html
    assert "관련 사이트" in html


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


def test_regular_user_has_mobile_safe_self_service_account_page(client):
    csrf = _get_csrf(client, "/login")
    client.post(
        "/login",
        data={
            "username": "employee",
            "password": "employee-password-123",
            "csrf_token": csrf,
        },
    )
    response = client.get("/account")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "내 계정" in html
    assert "회원 탈퇴" in html
    assert "14일간 보관" in html
    assert 'class="account-profile-grid"' in html


def test_regular_user_withdrawal_disables_account_and_clears_session(client):
    from config import DASHBOARD_DB_FILE

    csrf = _get_csrf(client, "/login")
    client.post(
        "/login",
        data={
            "username": "employee",
            "password": "employee-password-123",
            "csrf_token": csrf,
        },
    )
    with client.session_transaction() as flask_session:
        csrf = flask_session["csrf_token"] = "withdraw-csrf"
    response = client.post(
        "/account/withdraw",
        data={"csrf_token": csrf, "confirmation": "탈퇴"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "withdrawn=1" in response.headers["Location"]
    with client.session_transaction() as flask_session:
        assert "user_id" not in flask_session

    import sqlite3

    connection = sqlite3.connect(DASHBOARD_DB_FILE)
    connection.row_factory = sqlite3.Row
    row = connection.execute(
        "SELECT * FROM dashboard_users WHERE username='employee'"
    ).fetchone()
    connection.close()
    assert row["is_active"] == 0
    assert row["approval_status"] == "withdrawal_pending"
    requested = datetime.fromisoformat(row["deletion_requested_at"])
    scheduled = datetime.fromisoformat(row["deletion_scheduled_at"])
    assert timedelta(days=13, hours=23) < scheduled - requested < timedelta(days=14, minutes=1)


def test_research_upload_form_requires_research_permission(client):
    from auth import MENU_PERMISSIONS
    from dashboard_db import queries
    from extensions import dashboard_db

    connection = dashboard_db()
    employee = queries.get_user_by_username(connection, "employee")
    queries.replace_user_permissions(
        connection,
        employee["id"],
        MENU_PERMISSIONS.keys(),
        set(MENU_PERMISSIONS) - {"research_library"},
        None,
    )
    connection.close()

    csrf = _get_csrf(client, "/login")
    client.post(
        "/login",
        data={
            "username": "employee",
            "password": "employee-password-123",
            "csrf_token": csrf,
        },
    )
    response = client.get("/library")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'class="library-upload"' not in html
    assert "등록·수정 권한은 없습니다" in html
    with client.session_transaction() as flask_session:
        flask_session["csrf_token"] = "research-csrf"
    assert client.post(
        "/library", data={"csrf_token": "research-csrf"}
    ).status_code == 403


def test_expired_withdrawal_is_anonymized_after_retention(db_connection):
    from dashboard_db import queries

    cursor = db_connection.execute(
        """
        INSERT INTO dashboard_users
            (username, password_hash, created_at, role, is_active, email,
             google_sub, name, picture_url, approval_status,
             deletion_requested_at, deletion_scheduled_at)
        VALUES ('leaving-user', 'hash', ?, 'user', 0, 'leaving@example.com',
                'google-sub-leaving', 'Leaving User', 'https://example.com/a.jpg',
                'withdrawal_pending', ?, ?)
        """,
        (
            "2026-07-01T00:00:00+09:00",
            "2026-07-10T00:00:00+09:00",
            "2026-07-24T00:00:00+09:00",
        ),
    )
    user_id = cursor.lastrowid
    db_connection.commit()

    assert queries.purge_expired_withdrawn_users(db_connection) == 1
    row = db_connection.execute(
        "SELECT * FROM dashboard_users WHERE id=?", (user_id,)
    ).fetchone()
    assert row["username"] == f"deleted-user-{user_id}"
    assert row["email"] is None
    assert row["google_sub"] is None
    assert row["name"] is None
    assert row["picture_url"] is None
    assert row["approval_status"] == "deleted"
    assert row["deleted_at"]


def test_admin_can_restore_withdrawal_during_retention(client):
    from extensions import dashboard_db

    connection = dashboard_db()
    connection.execute("UPDATE dashboard_users SET role='admin' WHERE username='admin'")
    connection.execute(
        """
        UPDATE dashboard_users
        SET is_active=0, approval_status='withdrawal_pending',
            deletion_requested_at='2026-08-01T00:00:00+09:00',
            deletion_scheduled_at='2099-08-15T00:00:00+09:00'
        WHERE username='employee'
        """
    )
    employee_id = connection.execute(
        "SELECT id FROM dashboard_users WHERE username='employee'"
    ).fetchone()["id"]
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
    with client.session_transaction() as flask_session:
        flask_session["csrf_token"] = "restore-csrf"
    response = client.post(
        f"/admin/users/{employee_id}/restore-withdrawal",
        data={"csrf_token": "restore-csrf"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    connection = dashboard_db()
    row = connection.execute(
        "SELECT * FROM dashboard_users WHERE id=?", (employee_id,)
    ).fetchone()
    connection.close()
    assert row["is_active"] == 1
    assert row["approval_status"] == "approved"
    assert row["deletion_requested_at"] is None
    assert row["deletion_scheduled_at"] is None

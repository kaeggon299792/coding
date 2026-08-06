import hashlib
import io
import json
import re
import sqlite3
from datetime import timedelta
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


def test_google_password_change_requires_recent_authentication(account_client):
    client, db_path = account_client
    _login(client)
    from utils import now_kst

    connection = sqlite3.connect(db_path)
    employee_id = connection.execute(
        "SELECT id FROM dashboard_users WHERE username='employee'"
    ).fetchone()[0]
    connection.execute(
        "UPDATE dashboard_users SET google_sub='google-test-user' WHERE id=?",
        (employee_id,),
    )
    connection.execute(
        "UPDATE dashboard_active_sessions SET created_at=? WHERE user_id=?",
        ((now_kst() - timedelta(minutes=30)).isoformat(), employee_id),
    )
    original_hash = connection.execute(
        "SELECT password_hash FROM dashboard_users WHERE id=?", (employee_id,)
    ).fetchone()[0]
    connection.commit()
    connection.close()

    response = client.post(
        "/account/password",
        data={
            "csrf_token": _csrf(client, "/account"),
            "current_password": "",
            "new_password": "New-password-123!",
            "new_password_confirmation": "New-password-123!",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302

    assert "error=" in response.headers["Location"]
    connection = sqlite3.connect(db_path)
    current_hash = connection.execute(
        "SELECT password_hash FROM dashboard_users WHERE id=?", (employee_id,)
    ).fetchone()[0]
    connection.close()
    assert current_hash == original_hash


def test_admin_password_reset_revokes_remember_login(account_client):
    client, db_path = account_client
    _login(client, remember=True)
    with client.session_transaction() as flask_session:
        flask_session.clear()
    client.delete_cookie("casino_in_remember")

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
    connection = sqlite3.connect(db_path)
    employee_id = connection.execute(
        "SELECT id FROM dashboard_users WHERE username='employee'"
    ).fetchone()[0]
    connection.close()

    response = client.post(
        f"/admin/users/{employee_id}/password",
        data={"csrf_token": _csrf(client, "/admin/users"), "new_password": "Reset-password-123!"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    connection = sqlite3.connect(db_path)
    active_tokens = connection.execute(
        "SELECT COUNT(*) FROM remember_login_tokens WHERE user_id=? AND revoked_at IS NULL",
        (employee_id,),
    ).fetchone()[0]
    connection.close()
    assert active_tokens == 0


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
    assert "three.r149.min.js" not in html


def test_webgl_bundle_is_limited_to_home(account_client):
    client, _ = account_client
    home = client.get("/").get_data(as_text=True)
    login = client.get("/login").get_data(as_text=True)
    assert "three.r149.min.js" in home
    assert "casino-wave-webgl-v2.js" in home
    assert "three.r149.min.js" not in login
    assert "casino-wave-webgl-v2.js" not in login


def test_admin_portal_requires_admin_and_renders_daily_metrics(account_client, monkeypatch, tmp_path):
    client, db_path = account_client
    _login(client)
    assert client.get("/admin").status_code == 403

    client.post("/logout", data={"csrf_token": _csrf(client, "/account")})
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
    sharepoint_dir = tmp_path / "sharepoint"
    portfolio_dir = tmp_path / "portfolio"
    (portfolio_dir / "static" / "data").mkdir(parents=True)
    (portfolio_dir / "private_data").mkdir(parents=True)
    (portfolio_dir / "static" / "data" / "projects.json").write_text("[]", encoding="utf-8")
    (portfolio_dir / "static" / "data" / "skills.json").write_text("[]", encoding="utf-8")
    for name, value in (("about.json", {}), ("contact.json", {}), ("logos.json", [])):
        (portfolio_dir / "private_data" / name).write_text(
            json.dumps(value), encoding="utf-8"
        )
    monkeypatch.setattr("config.PORTFOLIO_SHAREPOINT_DIR", str(sharepoint_dir))
    monkeypatch.setattr("config.PORTFOLIO_APP_DIR", str(portfolio_dir))
    portfolio = client.get("/admin/portfolio")
    assert portfolio.status_code == 200
    portfolio_html = portfolio.get_data(as_text=True)
    assert "포트폴리오 관리" in portfolio_html
    assert "외부 링크 파일" in portfolio_html
    assert 'class="admin-portfolio-layout"' in portfolio_html
    assert 'data-portfolio-target="projects"' in portfolio_html
    assert 'data-portfolio-view="projects"' in portfolio_html
    assert 'src="https://www.shingoon.me/admin"' not in portfolio_html
    assert "https://www.shingoon.me" not in portfolio.headers["Content-Security-Policy"]
    for marker in (
        "프로젝트", "소개·프로필", "연락처", "회사·서비스 로고",
        "기술·역량", "Tips 콘텐츠", "외부 링크 파일",
    ):
        assert marker in portfolio_html
    saved_project = client.post(
        "/admin/portfolio/projects/save",
        data={
            "csrf_token": _csrf(client, "/admin/portfolio"),
            "title": "통합 관리 프로젝트",
            "summary": "CASINO IN에서 관리",
            "date": "2026",
        },
        follow_redirects=True,
    )
    assert saved_project.status_code == 200
    records = json.loads(
        (portfolio_dir / "static" / "data" / "projects.json").read_text("utf-8")
    )
    assert records[0]["title"] == "통합 관리 프로젝트"
    saved_contact = client.post(
        "/admin/portfolio/contact/save",
        data={
            "csrf_token": _csrf(client, "/admin/portfolio"),
            "phone": "0504-000-0000",
            "email": "admin@example.com",
            "website": "https://www.shingoon.me",
        },
        follow_redirects=True,
    )
    assert saved_contact.status_code == 200
    contact = json.loads(
        (portfolio_dir / "private_data" / "contact.json").read_text("utf-8")
    )
    assert contact["email"] == "admin@example.com"
    csrf_token = _csrf(client, "/admin/portfolio")
    uploaded = client.post(
        "/admin/portfolio/files",
        data={
            "csrf_token": csrf_token,
            "file": (io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"x" * 20), "sample.png"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert uploaded.status_code == 200
    assert "sample.png" in uploaded.get_data(as_text=True)
    assert (sharepoint_dir / "sample.png").is_file()
    deleted = client.post(
        "/admin/portfolio/files/delete",
        data={"csrf_token": _csrf(client, "/admin/portfolio"), "filename": "sample.png"},
        follow_redirects=True,
    )
    assert deleted.status_code == 200
    assert not (sharepoint_dir / "sample.png").exists()

    from utils import now_kst

    today = now_kst().date().isoformat()
    old_date = "2025-01-01T09:00:00+09:00"
    connection = sqlite3.connect(db_path)
    admin_id = connection.execute(
        "SELECT id FROM dashboard_users WHERE username='admin'"
    ).fetchone()[0]
    connection.execute(
        """
        INSERT INTO community_posts
            (author_id, author_username, title, content, created_at, updated_at,
             is_deleted, board_type)
        VALUES (?, 'admin', '오늘 공지', '내용', ?, ?, 0, 'notice')
        """,
        (admin_id, f"{today}T10:00:00+09:00", f"{today}T10:00:00+09:00"),
    )
    connection.execute(
        """
        INSERT INTO action_items
            (title, source_type, created_at, updated_at, priority, status,
             approved_by_user)
        VALUES ('오늘 건의', 'bug_report', ?, ?, 'normal', 'not_started', 1)
        """,
        (f"{today}T11:00:00+09:00", f"{today}T11:00:00+09:00"),
    )
    connection.execute(
        """
        INSERT INTO dashboard_users
            (username, password_hash, role, is_active, approval_status,
             created_at, deletion_requested_at, deleted_at)
        VALUES ('withdrawn', '!', 'user', 0, 'deleted', ?, ?, ?)
        """,
        (old_date, f"{today}T12:00:00+09:00", f"{today}T12:01:00+09:00"),
    )
    connection.commit()
    connection.close()

    page = client.get("/admin")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'data-metric="new-members">2<' in html
    assert 'data-metric="total-members">2<' in html
    assert 'data-metric="new-posts">2<' in html
    assert 'data-metric="withdrawals">1<' in html
    assert "최근 7일 활동" in html
    assert html.count('class="admin-activity-day"') == 7
    assert "7일 신규 가입" in html

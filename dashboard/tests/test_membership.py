import io

import pytest

from services import membership


def _create_user(connection, username, role="user", level="gold"):
    cursor = connection.execute(
        """INSERT INTO dashboard_users
           (username, password_hash, role, membership_level, is_active, created_at)
           VALUES (?, 'unused', ?, ?, 1, '2026-08-06T00:00:00')""",
        (username, role, level),
    )
    connection.commit()
    return cursor.lastrowid


def test_default_grades_and_board_policy(db_connection):
    grades = membership.list_grades(db_connection)
    assert [grade["code"] for grade in grades] == [
        "silver", "gold", "platinum", "diamond", "black"
    ]
    assert membership.can_board(db_connection, "community", "read") is True
    assert membership.can_board(db_connection, "community", "write") is False
    user_id = _create_user(db_connection, "gold-user")
    assert membership.can_board(
        db_connection, "community", "write", user_id, "user"
    ) is True
    policies = {
        row["board_key"]: row for row in membership.list_board_permissions(db_connection)
    }
    assert policies["benefits"]["board_label"] == "복지게시판"
    assert policies["recruitment_guide"]["board_label"] == "족보게시판"
    assert policies["source_data"]["read_grade"] == "gold"
    assert membership.can_board(db_connection, "benefits", "write") is False
    assert membership.can_board(
        db_connection, "source_data", "read", user_id, "user"
    ) is True


def test_black_grade_is_reserved_for_admin(db_connection):
    user_id = _create_user(db_connection, "regular")
    admin_id = _create_user(db_connection, "administrator", "admin", "black")
    with pytest.raises(ValueError, match="관리자 역할"):
        membership.update_user_grade(db_connection, user_id, "black", admin_id)
    with pytest.raises(ValueError, match="Black"):
        membership.update_user_grade(db_connection, admin_id, "gold", admin_id)


def test_board_policy_cannot_make_write_easier_than_read(db_connection):
    with pytest.raises(ValueError, match="낮을 수 없습니다"):
        membership.update_board_permission(
            db_connection, "community", "platinum", "gold", "platinum", 1
        )
    with pytest.raises(ValueError, match="Gold 이상"):
        membership.update_board_permission(
            db_connection, "source_data", "silver", "black", "black", 1
        )


class _Upload:
    def __init__(self, filename, data):
        self.filename = filename
        self.stream = io.BytesIO(data)


def test_svg_icon_rejects_script(db_connection):
    upload = _Upload(
        "badge.svg",
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    )
    with pytest.raises(ValueError, match="실행 가능한"):
        membership.save_grade_icon(db_connection, "gold", upload, 1)


def test_png_icon_rejects_fake_file(db_connection):
    with pytest.raises(ValueError, match="올바른 PNG"):
        membership.save_grade_icon(
            db_connection, "gold", _Upload("badge.png", b"not-a-png"), 1
        )


def test_grade_name_can_change_without_changing_icon(db_connection):
    before = next(
        grade for grade in membership.list_grades(db_connection) if grade["code"] == "gold"
    )
    membership.update_grade_text(
        db_connection, "gold", "Starter", "가입 기본등급", 1
    )
    db_connection.commit()
    after = next(
        grade for grade in membership.list_grades(db_connection) if grade["code"] == "gold"
    )
    assert after["label"] == "Starter"
    assert after["description"] == "가입 기본등급"
    assert after["icon_path"] == before["icon_path"]


def test_membership_admin_page_requires_admin_and_renders(monkeypatch, tmp_path):
    db_path = tmp_path / "membership-admin.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    import app as app_module
    from dashboard_db import schema

    connection = schema.connect(str(db_path))
    admin_id = _create_user(connection, "membership-admin", "admin", "black")
    user_id = _create_user(connection, "membership-user", "user", "gold")
    connection.close()
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        assert client.get("/admin/membership").status_code == 302
        with client.session_transaction() as session:
            session["user_id"] = user_id
            session["username"] = "membership-user"
            session["role"] = "user"
        assert client.get("/admin/membership").status_code == 403
        assert client.post(
            f"/admin/membership/users/{user_id}",
            data={"csrf_token": "a" * 64, "membership_level": "platinum"},
        ).status_code == 403
        with client.session_transaction() as session:
            session["user_id"] = admin_id
            session["username"] = "membership-admin"
            session["role"] = "admin"
            session["csrf_token"] = "a" * 64
        response = client.get("/admin/membership")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "회원관리" in html
        assert "가입일" in html
        assert "방문횟수" in html
        assert "최종 로그인" in html
        assert "게시판별 등급 권한" in html
        assert "membership-user" in html
        detail = client.get(f"/admin/membership/users/{user_id}")
        assert detail.status_code == 200
        detail_html = detail.get_data(as_text=True)
        assert "회원 등급 조정" in detail_html
        assert "membership-user" in detail_html
        assert client.get("/admin/membership/users/999999").status_code == 404
        assert client.post(
            f"/admin/membership/users/{user_id}",
            data={"membership_level": "platinum"},
        ).status_code == 400
        changed = client.post(
            f"/admin/membership/users/{user_id}",
            data={"csrf_token": "a" * 64, "membership_level": "platinum"},
            follow_redirects=False,
        )
        assert changed.status_code == 302
        assert f"/admin/membership/users/{user_id}" in changed.headers["Location"]

    connection = schema.connect(str(db_path))
    assert connection.execute(
        "SELECT membership_level FROM dashboard_users WHERE id=?", (user_id,)
    ).fetchone()["membership_level"] == "platinum"
    connection.close()

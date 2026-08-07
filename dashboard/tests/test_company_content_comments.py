import pytest

import app as app_module
from dashboard_db import queries, schema


def _user(connection, username, role="user"):
    user_id = connection.execute(
        """INSERT INTO dashboard_users
               (username, password_hash, role, is_active, created_at, updated_at)
           VALUES (?, 'unused', ?, 1, '2026-08-04', '2026-08-04')""",
        (username, role),
    ).lastrowid
    connection.commit()
    return user_id


def _benefit(connection):
    return queries.create_company_benefit(
        connection,
        {
            "company_name": "파라다이스",
            "category": "family",
            "benefit_name": "직장 어린이집",
            "support_value": "회사 운영",
            "benefit_level": "임직원 자녀",
            "notes": "",
            "effective_from": "2026-01-01",
            "ended_on": None,
        },
    )


def _guide(connection):
    return queries.create_company_recruitment_guide(
        connection,
        {
            "company_name": "파라다이스",
            "process_type": "interview",
            "position_name": "카지노 딜러",
            "stage_name": "1차 면접",
            "question_text": "고객 응대 경험을 말해주세요.",
            "atmosphere": "차분함",
            "experience_period": "2026-07",
            "notes": "",
        },
    )


def test_company_content_comments_support_one_level_replies_and_soft_delete(tmp_path):
    connection = schema.connect(str(tmp_path / "comments.db"))
    user_id = _user(connection, "commenter")
    benefit_id = _benefit(connection)
    root_id = queries.create_company_content_comment(
        connection, "benefit", benefit_id, user_id, "commenter", "지원 대상이 궁금합니다."
    )
    reply_id = queries.create_company_content_comment(
        connection, "benefit", benefit_id, user_id, "commenter", "임직원 자녀 대상입니다.",
        parent_id=root_id,
    )
    with pytest.raises(ValueError):
        queries.create_company_content_comment(
            connection, "benefit", benefit_id, user_id, "commenter", "3단계 답글",
            parent_id=reply_id,
        )
    queries.soft_delete_company_content_comment(connection, root_id, user_id)
    grouped = app_module._group_company_comment_threads(
        queries.list_company_content_comments(connection, "benefit")
    )
    assert grouped[benefit_id]["count"] == 1
    assert grouped[benefit_id]["threads"][0]["is_deleted"] == 1
    assert grouped[benefit_id]["threads"][0]["replies"][0]["id"] == reply_id
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    connection.close()


def test_benefit_and_guide_comment_routes_require_login_and_support_replies(monkeypatch, tmp_path):
    db_path = tmp_path / "comment-routes.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    connection = schema.connect(str(db_path))
    user_id = _user(connection, "writer")
    benefit_id = _benefit(connection)
    guide_id = _guide(connection)
    connection.close()

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        public_benefits = client.get("/companies/benefits").get_data(as_text=True)
        public_guides = client.get("/companies/recruitment-guide").get_data(as_text=True)
        assert "댓글 작성은 로그인 후" in public_benefits
        assert "댓글 작성은 로그인 후" in public_guides
        denied = client.post(
            f"/companies/comments/benefit/{benefit_id}", data={"content": "댓글"}
        )
        assert denied.status_code == 302
        assert "/login" in denied.headers["Location"]

        with client.session_transaction() as browser_session:
            browser_session["user_id"] = user_id
            browser_session["username"] = "writer"
            browser_session["role"] = "user"
            browser_session["csrf_token"] = "d" * 64

        root_response = client.post(
            f"/companies/comments/benefit/{benefit_id}",
            data={
                "csrf_token": "d" * 64,
                "content": "<script>운영 시간이 궁금합니다.</script>",
                "notification_email": "private-comment@example.com",
            },
        )
        assert root_response.status_code == 302
        connection = schema.connect(str(db_path))
        root_id = queries.list_company_content_comments(
            connection, "benefit", benefit_id
        )[0]["id"]
        connection.close()
        reply_response = client.post(
            f"/companies/comments/benefit/{benefit_id}",
            data={
                "csrf_token": "d" * 64,
                "parent_id": str(root_id),
                "content": "평일 운영입니다.",
            },
        )
        assert reply_response.status_code == 302
        benefit_html = client.get("/companies/benefits").get_data(as_text=True)
        assert "&lt;script&gt;운영 시간이 궁금합니다.&lt;/script&gt;" in benefit_html
        assert "평일 운영입니다." in benefit_html
        assert "private-comment@example.com" not in benefit_html
        assert "새 댓글 알림은 Telegram을 연결한 대화 참여자에게 전송됩니다." in benefit_html

        legacy_email_field = client.post(
            f"/companies/comments/benefit/{benefit_id}",
            data={
                "csrf_token": "d" * 64,
                "content": "등록되면 안 되는 댓글",
                "notification_email": "invalid-address",
            },
        )
        assert legacy_email_field.status_code == 302
        # The retired email field is ignored; it no longer blocks a valid comment.
        assert "등록되면 안 되는 댓글" in client.get(
            "/companies/benefits"
        ).get_data(as_text=True)

        guide_response = client.post(
            f"/companies/comments/recruitment_guide/{guide_id}",
            data={"csrf_token": "d" * 64, "content": "추가 질문도 있었나요?"},
        )
        assert guide_response.status_code == 302
        assert "추가 질문도 있었나요?" in client.get(
            "/companies/recruitment-guide"
        ).get_data(as_text=True)


def test_comment_delete_is_limited_to_owner_or_admin(monkeypatch, tmp_path):
    db_path = tmp_path / "comment-delete.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    connection = schema.connect(str(db_path))
    owner_id = _user(connection, "owner")
    other_id = _user(connection, "other")
    benefit_id = _benefit(connection)
    comment_id = queries.create_company_content_comment(
        connection, "benefit", benefit_id, owner_id, "owner", "작성자 댓글"
    )
    connection.close()

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        with client.session_transaction() as browser_session:
            browser_session["user_id"] = other_id
            browser_session["username"] = "other"
            browser_session["role"] = "user"
            browser_session["csrf_token"] = "e" * 64
        forbidden = client.post(
            f"/companies/comments/benefit/{benefit_id}/{comment_id}/delete",
            data={"csrf_token": "e" * 64},
        )
        assert forbidden.status_code == 403

        with client.session_transaction() as browser_session:
            browser_session["user_id"] = owner_id
            browser_session["username"] = "owner"
            browser_session["role"] = "user"
            browser_session["csrf_token"] = "f" * 64
        deleted = client.post(
            f"/companies/comments/benefit/{benefit_id}/{comment_id}/delete",
            data={"csrf_token": "f" * 64},
        )
        assert deleted.status_code == 302

    connection = schema.connect(str(db_path))
    assert queries.get_company_content_comment(connection, comment_id)["is_deleted"] == 1
    connection.close()

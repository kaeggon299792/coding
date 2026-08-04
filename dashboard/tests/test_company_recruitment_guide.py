from pathlib import Path

import app as app_module
from dashboard_db import queries, schema


def _admin(connection):
    user_id = connection.execute(
        """INSERT INTO dashboard_users
               (username, password_hash, role, is_active, created_at, updated_at)
           VALUES ('guide-admin', 'unused', 'admin', 1, '2026-08-04', '2026-08-04')"""
    ).lastrowid
    connection.commit()
    return user_id


def _guide_form(csrf_token, **overrides):
    values = {
        "csrf_token": csrf_token,
        "company_name": "파라다이스",
        "process_type": "interview",
        "position_name": "카지노 딜러",
        "stage_name": "1차 실무면접",
        "question_text": "고객이 게임 결과에 항의할 때 어떻게 대응하겠습니까?",
        "atmosphere": "면접관 3명, 차분하지만 추가 질문이 많았음",
        "experience_period": "2026-07",
        "notes": "고객 응대 경험을 구체적으로 준비",
    }
    values.update(overrides)
    return values


def test_recruitment_guide_schema_queries_and_duplicate(tmp_path):
    connection = schema.connect(str(tmp_path / "guide.db"))
    guide_id = queries.create_company_recruitment_guide(
        connection,
        {
            "company_name": "파라다이스",
            "process_type": "practical",
            "position_name": "카지노 딜러",
            "stage_name": "실기",
            "question_text": "칩스 커팅과 카드 핸들링",
            "atmosphere": "순서대로 개별 평가",
            "experience_period": "2026-06",
            "notes": "정확성과 속도를 함께 평가",
        },
    )
    assert queries.get_company_recruitment_guide(connection, guide_id)["process_type"] == "practical"
    assert queries.list_company_recruitment_guides(connection, "파라다이스")[0]["question_text"] == "칩스 커팅과 카드 핸들링"
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    connection.close()


def test_recruitment_guide_public_read_and_admin_management(monkeypatch, tmp_path):
    db_path = tmp_path / "guide-routes.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    connection = schema.connect(str(db_path))
    admin_id = _admin(connection)
    connection.close()

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        public = client.get("/companies/recruitment-guide")
        public_html = public.get_data(as_text=True)
        assert public.status_code == 200
        assert "기업별 채용 족보" in public_html
        assert "채용 족보 등록" not in public_html
        denied = client.post("/companies/recruitment-guide", data={})
        assert denied.status_code == 302
        assert "/login" in denied.headers["Location"]

        with client.session_transaction() as browser_session:
            browser_session["user_id"] = admin_id
            browser_session["username"] = "guide-admin"
            browser_session["role"] = "admin"
            browser_session["csrf_token"] = "c" * 64

        assert "채용 족보 등록" in client.get("/companies/recruitment-guide").get_data(as_text=True)
        assert client.post(
            "/companies/recruitment-guide", data=_guide_form("c" * 64)
        ).status_code == 302
        assert client.post(
            "/companies/recruitment-guide", data=_guide_form("c" * 64)
        ).status_code == 302

        connection = schema.connect(str(db_path))
        rows = queries.list_company_recruitment_guides(connection, "파라다이스")
        assert len(rows) == 1
        guide_id = rows[0]["id"]
        connection.close()

        edited = client.post(
            f"/companies/recruitment-guide/{guide_id}/edit",
            data=_guide_form("c" * 64, atmosphere="편안한 분위기"),
        )
        assert edited.status_code == 302
        html = client.get(
            "/companies/recruitment-guide?company=파라다이스"
        ).get_data(as_text=True)
        assert "고객이 게임 결과에 항의할 때" in html
        assert "편안한 분위기" in html


def test_recruitment_guide_navigation_and_template_contract():
    root = Path(__file__).parents[1]
    subnav = (root / "templates" / "_data_subnav.html").read_text(encoding="utf-8")
    template = (root / "templates" / "company_recruitment_guide.html").read_text(encoding="utf-8")
    css = (root / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")
    recruitment_link = "url_for('recruitment_page')"
    guide_link = "url_for('company_recruitment_guide_page')"
    assert subnav.index(recruitment_link) < subnav.index(guide_link)
    assert ">족보</a>" in subnav
    assert "current_user_role == 'admin'" in template
    assert "개인정보는 등록하지 마세요" in template
    assert ".recruitment-guide-card" in css
    app_module.app.jinja_env.get_template("company_recruitment_guide.html")

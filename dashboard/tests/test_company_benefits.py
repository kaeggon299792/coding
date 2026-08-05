from pathlib import Path

import app as app_module
from dashboard_db import queries, schema


def _admin(connection):
    user_id = connection.execute(
        """INSERT INTO dashboard_users
               (username, password_hash, role, is_active, created_at, updated_at)
           VALUES ('benefits-admin', 'unused', 'admin', 1, '2026-08-04', '2026-08-04')"""
    ).lastrowid
    connection.commit()
    return user_id


def _benefit_form(csrf_token, **overrides):
    values = {
        "csrf_token": csrf_token,
        "company_name": "파라다이스",
        "category": "family",
        "benefit_name": "직장 어린이집",
        "support_value": "회사 운영 어린이집 이용",
        "benefit_level": "임직원 자녀 지원",
        "notes": "세부 조건은 사내 규정 기준",
        "effective_from": "2026-01-01",
        "ended_on": "",
    }
    values.update(overrides)
    return values


def test_company_benefit_schema_queries_and_end_history(tmp_path):
    connection = schema.connect(str(tmp_path / "benefits.db"))
    benefit_id = queries.create_company_benefit(
        connection,
        {
            "company_name": "파라다이스",
            "category": "financial",
            "benefit_name": "복지카드",
            "support_value": "연 120만원",
            "benefit_level": "연간",
            "notes": "선택적 복지",
            "effective_from": "2026-01-01",
            "ended_on": None,
        },
    )
    assert queries.get_company_benefit(connection, benefit_id)["support_value"] == "연 120만원"
    queries.end_company_benefit(connection, benefit_id, "2026-12-31")
    ended = queries.list_company_benefits(connection, "파라다이스")[0]
    assert ended["ended_on"] == "2026-12-31"
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    connection.close()


def test_company_benefits_admin_registration_duplicate_and_end_history(monkeypatch, tmp_path):
    db_path = tmp_path / "benefit-routes.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    connection = schema.connect(str(db_path))
    admin_id = _admin(connection)
    connection.close()

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        public = client.get("/companies/benefits")
        assert public.status_code == 200
        assert "기업별 복리후생" in public.get_data(as_text=True)
        assert "복리후생 등록" not in public.get_data(as_text=True)
        denied = client.post("/companies/benefits", data={})
        assert denied.status_code == 302
        assert "/login" in denied.headers["Location"]

        with client.session_transaction() as browser_session:
            browser_session["user_id"] = admin_id
            browser_session["username"] = "benefits-admin"
            browser_session["role"] = "admin"
            browser_session["csrf_token"] = "b" * 64

        admin_page = client.get("/companies/benefits")
        assert "복리후생 등록" in admin_page.get_data(as_text=True)
        assert client.post(
            "/companies/benefits", data=_benefit_form("b" * 64)
        ).status_code == 302
        assert client.post(
            "/companies/benefits", data=_benefit_form("b" * 64)
        ).status_code == 302

        connection = schema.connect(str(db_path))
        rows = queries.list_company_benefits(connection, "파라다이스")
        assert len(rows) == 1
        benefit_id = rows[0]["id"]
        connection.close()

        ended = client.post(
            f"/companies/benefits/{benefit_id}/end",
            data={
                "csrf_token": "b" * 64,
                "company_name": "파라다이스",
                "ended_on": "2026-08-04",
            },
        )
        assert ended.status_code == 302
        history = client.get("/companies/benefits?company=파라다이스")
        html = history.get_data(as_text=True)
        assert "<s>직장 어린이집</s>" in html
        assert "종료일 2026-08-04" in html


def test_company_benefits_navigation_and_template_contract():
    root = Path(__file__).parents[1]
    subnav = (root / "templates" / "_data_subnav.html").read_text(encoding="utf-8")
    template = (root / "templates" / "company_benefits.html").read_text(encoding="utf-8")
    css = (root / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")
    base = (root / "templates" / "base.html").read_text(encoding="utf-8")
    assert "company_benefits_page" in subnav
    assert ">복리후생</a>" in subnav
    assert "benefit.ended_on" in template
    assert "<s>{{ t(benefit.benefit_name) }}</s>" in template
    assert 'name="effective_from"' not in template
    assert template.count('name="ended_on"') == 1
    assert "종료 이력 남기기" in template
    assert ".company-benefit-card.is-ended" in css
    assert "data-sticky-nav-toggle" in subnav
    assert 'html[data-sticky-nav="true"] .topbar' in css
    assert 'html[data-sticky-nav="true"] .data-subnav' in css
    assert 'casino-in-sticky-nav' in base
    app_module.app.jinja_env.get_template("company_benefits.html")


def test_sticky_navigation_is_not_limited_to_one_viewport():
    root = Path(__file__).parents[1]
    css = (root / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")
    base = (root / "templates" / "base.html").read_text(encoding="utf-8")

    assert "html { height: 100%; }" in css
    assert "body { min-height: 100%; }" in css
    assert "html, body { height: 100%; }" not in css
    assert "dashboard.css') }}?v=20260806-diary-mood2" in base

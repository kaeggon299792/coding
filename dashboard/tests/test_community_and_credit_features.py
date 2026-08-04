import json
from pathlib import Path

import pytest

import app as app_module
from dashboard_db import queries
from scripts.import_company_credit_ratings import import_ratings
from scripts.import_company_executive_profiles import import_profiles
from scripts.backfill_dart_disclosures import _date_windows
from services import company_intelligence


def _user(connection, username="member"):
    user_id = connection.execute(
        """
        INSERT INTO dashboard_users
            (username, password_hash, role, is_active, created_at, updated_at)
        VALUES (?, 'hash', 'user', 1, '2026-08-03', '2026-08-03')
        """,
        (username,),
    ).lastrowid
    connection.commit()
    return user_id


def test_markdown_is_rendered_and_dangerous_html_is_removed():
    rendered = str(app_module._render_community_markdown(
        "## 제목\n\n**강조** [안전](https://example.com) "
        "<script>alert(1)</script> [위험](javascript:alert(1))"
    ))
    assert "<h2>제목</h2>" in rendered
    assert "<strong>강조</strong>" in rendered
    assert 'href="https://example.com"' in rendered
    assert "<script" not in rendered
    assert "javascript:" not in rendered


def test_attachment_links_require_safe_https_and_expected_extension():
    assert app_module._community_attachment_url(
        "https://cdn.example.com/photo.webp", "image"
    ).endswith(".webp")
    assert app_module._community_attachment_url(
        "https://cdn.example.com/report.pdf", "pdf"
    ).endswith(".pdf")
    for value, kind in (
        ("http://example.com/a.png", "image"),
        ("https://user:pass@example.com/a.png", "image"),
        ("https://example.com/a.exe", "image"),
        ("https://example.com/report.html", "pdf"),
    ):
        with pytest.raises(ValueError):
            app_module._community_attachment_url(value, kind)


def test_board_types_and_recommendation_toggle(db_connection):
    user_id = _user(db_connection)
    community_id = queries.create_community_post(
        db_connection, user_id, "member", "자유글", "본문",
        board_type="community",
    )
    notice_id = queries.create_community_post(
        db_connection, user_id, "member", "공지", "본문",
        board_type="notice",
    )
    assert [row["id"] for row in queries.list_community_posts(
        db_connection, board_type="community"
    )] == [community_id]
    assert [row["id"] for row in queries.list_community_posts(
        db_connection, board_type="notice"
    )] == [notice_id]

    assert queries.toggle_community_post_recommendation(
        db_connection, community_id, user_id
    ) == (True, 1)
    post = queries.get_community_post(db_connection, community_id, user_id=user_id)
    assert post["recommended_by_current_user"] == 1
    assert post["recommendation_count"] == 1
    assert queries.toggle_community_post_recommendation(
        db_connection, community_id, user_id
    ) == (False, 0)


def test_credit_rating_import_and_latest_lookup(tmp_path):
    db_path = tmp_path / "dashboard.db"
    data_path = tmp_path / "ratings.json"
    data_path.write_text(json.dumps({
        "schema_version": 1,
        "ratings": [
            {"company_name": "파라다이스", "rating": "A0", "evaluated_on": "2025-11-21", "financial_as_of": None, "rating_type": "회사채등급", "agency": "NICE", "source_label": "나이스신용평가"},
            {"company_name": "파라다이스", "rating": "A+", "evaluated_on": "2026-04-20", "financial_as_of": None, "rating_type": "회사채등급", "agency": "NICE", "source_label": "나이스신용평가"},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    first = import_ratings(db_path, data_path)
    second = import_ratings(db_path, data_path)
    assert first == second == {"companies": 1, "ratings": 2, "integrity": "ok"}
    from dashboard_db import schema
    connection = schema.connect(str(db_path))
    assert queries.get_latest_company_credit_rating(
        connection, "파라다이스"
    )["rating"] == "A+"
    connection.close()


def test_kangwonland_credit_history_keeps_all_data_but_displays_five_years(tmp_path):
    db_path = tmp_path / "dashboard.db"
    data_path = (
        Path(__file__).parents[1]
        / "data"
        / "company_credit_ratings_kangwonland_20260804.json"
    )
    result = import_ratings(db_path, data_path)
    assert result == {"companies": 1, "ratings": 40, "integrity": "ok"}

    from dashboard_db import schema
    connection = schema.connect(str(db_path))
    rows = queries.list_company_credit_ratings(connection, "강원랜드")
    assert rows[0]["rating"] == "A0"
    visible = company_intelligence._latest_five_years(rows)
    assert len(visible) == 7
    assert {row["evaluated_on"][:4] for row in visible} == {
        "2016", "2017", "2018", "2019", "2020"
    }
    assert len(rows) == 40
    connection.close()


def test_company_rating_badge_is_prominent_and_responsive():
    css = (Path(__file__).parents[1] / "static" / "css" / "dashboard.css").read_text(
        encoding="utf-8"
    )
    rule = css.split(".company-rating-badge strong {", 1)[1].split("}", 1)[0]
    assert "font-size: clamp(28px, 2.2vw, 32px);" in rule
    assert "font-weight: 800;" in rule
    badge_rule = css.split(".company-rating-badge {", 1)[1].split("}", 1)[0]
    source_rule = css.rsplit(".company-rating-badge small {", 1)[1].split("}", 1)[0]
    assert "display: inline-grid;" in badge_rule
    assert "grid-template-columns: auto auto;" in badge_rule
    assert "grid-column: 1 / -1;" in source_rule
    template = (Path(__file__).parents[1] / "templates" / "companies.html").read_text(
        encoding="utf-8"
    )
    assert 'class="rating-zero"' in template
    assert ".company-rating-badge .rating-zero::after" in css


def test_company_executive_profiles_support_single_and_joint_representatives(tmp_path):
    db_path = tmp_path / "dashboard.db"
    data_path = (
        Path(__file__).parents[1] / "data" / "company_executive_profiles_20260804.json"
    )
    first = import_profiles(db_path, data_path)
    second = import_profiles(db_path, data_path)
    assert first == second == {"companies": 2, "profiles": 4, "integrity": "ok"}

    from dashboard_db import schema
    connection = schema.connect(str(db_path))
    gkl = queries.list_latest_company_executive_profiles(connection, "GKL")
    lotte = queries.list_latest_company_executive_profiles(connection, "롯데관광개발")
    assert [(row["executive_name"], row["appointed_on"]) for row in gkl] == [
        ("윤두현", "2024-12-02")
    ]
    assert [row["executive_name"] for row in lotte] == ["김기병", "백현", "김한준"]
    assert lotte[0]["appointed_on"] is None
    connection.close()


def test_company_detail_template_renders_responsive_executive_profiles():
    root = Path(__file__).parents[1]
    template = (root / "templates" / "company_detail.html").read_text(encoding="utf-8")
    css = (root / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")
    assert "company-executive-grid" in template
    assert "executive.birth_date" in template
    assert ".company-executive-grid { grid-template-columns: 1fr; }" in css


def test_company_news_flags_are_derived_from_ai_fields():
    item = company_intelligence._decorate_company_news({
        "importance_score": 72,
        "importance": "high",
        "latest_summary": "AI 요약",
        "impact_direction": "negative",
    })
    assert item["is_important"] is True
    assert item["is_analyzed"] is True
    assert item["impact_code"] == "negative"


def test_company_jobs_and_market_data_do_not_use_news_signals():
    profiles = [
        {"name": "\ud30c\ub77c\ub2e4\uc774\uc2a4", "aliases": ["\ud30c\ub77c\ub2e4\uc774\uc2a4"]},
        {"name": "\ud30c\ub77c\ub2e4\uc774\uc2a4\uc138\uac00\uc0ac\ubbf8", "aliases": ["\ud30c\ub77c\ub2e4\uc774\uc2a4\uc2dc\ud2f0"]},
    ]
    jobs = [
        {"title": "\ud30c\ub77c\ub2e4\uc774\uc2a4\uc2dc\ud2f0 \uc2e0\uc785 \ucc44\uc6a9", "raw_text": "", "company_name": "", "ai_summary": ""},
        {"title": "\ud30c\ub77c\ub2e4\uc774\uc2a4 \ubcf8\uc0ac \ucc44\uc6a9", "raw_text": "", "company_name": "", "ai_summary": ""},
    ]
    assigned = company_intelligence._assign_recruitment_jobs(profiles, jobs)
    assert [item["title"] for item in assigned["\ud30c\ub77c\ub2e4\uc774\uc2a4\uc138\uac00\uc0ac\ubbf8"]] == [jobs[0]["title"]]
    assert [item["title"] for item in assigned["\ud30c\ub77c\ub2e4\uc774\uc2a4"]] == [jobs[1]["title"]]

    quote = company_intelligence._market_quote_for_company(
        profiles[0], {"stock_code": "034230"},
        [{"symbol": "034230", "name": "\ud30c\ub77c\ub2e4\uc774\uc2a4", "close_price": 9500}],
    )
    assert quote["close_price"] == 9500


def test_company_detail_requires_login():
    app_module.app.config.update(TESTING=True)
    response = app_module.app.test_client().get(
        "/companies/" + "\ud30c\ub77c\ub2e4\uc774\uc2a4",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_dart_backfill_windows_are_contiguous_and_bounded():
    from datetime import date

    windows = list(_date_windows(date(2023, 8, 4), date(2026, 8, 3)))
    assert windows[0][0] == date(2023, 8, 4)
    assert windows[-1][1] == date(2026, 8, 3)
    assert all((end - start).days < 180 for start, end in windows)
    assert all(windows[index][1] + __import__('datetime').timedelta(days=1) == windows[index + 1][0] for index in range(len(windows) - 1))


def test_board_error_and_changed_templates_render():
    app_module.app.config.update(TESTING=True)
    client = app_module.app.test_client()
    assert client.get("/board").status_code == 200
    assert client.get("/board/notices").status_code == 200
    response = client.get("/this-page-does-not-exist-20260803")
    assert response.status_code == 404
    assert "페이지를 찾을 수 없습니다" in response.get_data(as_text=True)
    with app_module.app.test_request_context("/test-error"):
        for status_code in (400, 403, 404, 405, 413, 500):
            _, rendered_status = app_module._render_error_page(status_code)
            assert rendered_status == status_code
    for template in (
        "_topbar.html", "_board_subnav.html", "community_board.html",
        "community_post.html", "companies.html", "company_detail.html",
        "company_news.html", "error.html",
    ):
        app_module.app.jinja_env.get_template(template)

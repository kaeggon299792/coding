import json
from pathlib import Path

import pytest

import app as app_module
from dashboard_db import queries
from scripts.import_company_credit_ratings import import_ratings
from scripts.import_company_executive_profiles import import_profiles
from scripts.backfill_dart_disclosures import _date_windows
from services import company_intelligence
from dashboard_db import schema


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
    pinned_id = queries.create_community_post(
        db_connection, user_id, "member", "상단 고정글", "본문",
        board_type="community", is_pinned=True,
    )
    notice_id = queries.create_community_post(
        db_connection, user_id, "member", "공지", "본문",
        board_type="notice",
    )
    assert [row["id"] for row in queries.list_community_posts(
        db_connection, board_type="community"
    )] == [pinned_id, community_id]
    assert [row["id"] for row in queries.list_community_posts(
        db_connection, board_type="notice"
    )] == [notice_id]
    assert queries.count_community_posts(db_connection, board_type="community") == 2
    queries.set_community_post_pinned(db_connection, pinned_id, False)
    assert queries.get_community_post(db_connection, pinned_id)["is_pinned"] == 0

    assert queries.toggle_community_post_recommendation(
        db_connection, community_id, user_id
    ) == (True, 1)
    post = queries.get_community_post(db_connection, community_id, user_id=user_id)
    assert post["recommended_by_current_user"] == 1
    assert post["recommendation_count"] == 1
    assert queries.toggle_community_post_recommendation(
        db_connection, community_id, user_id
    ) == (False, 0)
    assert queries.record_unique_community_post_view(
        db_connection, community_id, "viewer-a"
    ) is True
    assert queries.record_unique_community_post_view(
        db_connection, community_id, "viewer-a"
    ) is False
    assert queries.get_community_post(db_connection, community_id)["view_count"] == 1
    queries.update_community_post(
        db_connection, community_id, "수정된 제목", "수정된 본문"
    )
    assert queries.get_community_post(db_connection, community_id)["title"] == "수정된 제목"

    queries.soft_delete_community_post(db_connection, community_id, user_id)
    assert queries.get_community_post(db_connection, community_id) is None
    assert queries.count_community_posts(db_connection, board_type="community") == 1
    deleted = db_connection.execute(
        "SELECT is_deleted, deleted_by, deleted_at FROM community_posts WHERE id=?",
        (community_id,),
    ).fetchone()
    assert deleted["is_deleted"] == 1
    assert deleted["deleted_by"] == user_id
    assert deleted["deleted_at"]


def test_admin_notice_creation_and_owner_post_deletion_routes(monkeypatch, tmp_path):
    db_path = tmp_path / "community-routes.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    connection = schema.connect(str(db_path))
    owner_id = _user(connection, "post-owner")
    admin_id = connection.execute(
        """INSERT INTO dashboard_users
               (username, password_hash, role, is_active, created_at, updated_at)
           VALUES ('board-admin', 'hash', 'admin', 1, '2026-08-04', '2026-08-04')"""
    ).lastrowid
    connection.commit()
    connection.close()

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        with client.session_transaction() as browser_session:
            browser_session["user_id"] = owner_id
            browser_session["username"] = "post-owner"
            browser_session["role"] = "user"
            browser_session["csrf_token"] = "c" * 64
        created = client.post(
            "/board",
            data={
                "csrf_token": "c" * 64,
                "title": "일반 사용자의 글",
                "content": "일반 본문",
                "is_pinned": "1",
            },
        )
        assert created.status_code == 302
        owner_post_id = int(created.headers["Location"].rstrip("/").split("/")[-1])
        owner_page = client.get(f"/board/{owner_post_id}")
        assert "community-post-delete-button" in owner_page.get_data(as_text=True)
        assert f'/board/{owner_post_id}/edit' in owner_page.get_data(as_text=True)
        edited = client.post(
            f"/board/{owner_post_id}/edit",
            data={
                "csrf_token": "c" * 64, "title": "수정된 자유 글",
                "content": "수정된 본문",
            },
        )
        assert edited.status_code == 302
        assert client.post(
            f"/board/{owner_post_id}/pin",
            data={"csrf_token": "c" * 64, "is_pinned": "1"},
        ).status_code == 403
        assert client.post(
            f"/board/{owner_post_id}/delete",
            data={"csrf_token": "invalid"},
        ).status_code == 400

        with client.session_transaction() as browser_session:
            browser_session["user_id"] = admin_id
            browser_session["username"] = "board-admin"
            browser_session["role"] = "admin"
            browser_session["csrf_token"] = "a" * 64
        pinned = client.post(
            "/board",
            data={
                "csrf_token": "a" * 64,
                "title": "자유게시판 고정글",
                "content": "고정글 본문",
                "is_pinned": "1",
            },
        )
        assert pinned.status_code == 302
        pinned_id = int(pinned.headers["Location"].rstrip("/").split("/")[-1])
        notice = client.post(
            "/board/notices",
            data={
                "csrf_token": "a" * 64,
                "title": "공지사항 전용 글",
                "content": "공지 본문",
            },
        )
        assert notice.status_code == 302
        notice_id = int(notice.headers["Location"].rstrip("/").split("/")[-1])
        notice_edited = client.post(
            f"/board/{notice_id}/edit",
            data={
                "csrf_token": "a" * 64, "title": "수정된 공지",
                "content": "수정된 공지 본문",
            },
        )
        assert notice_edited.status_code == 302
        assert client.post(
            f"/board/{notice_id}/pin",
            data={"csrf_token": "a" * 64, "is_pinned": "1"},
        ).status_code == 404
        board_html = client.get("/board").get_data(as_text=True)
        notice_html = client.get("/board/notices").get_data(as_text=True)
        assert "LATEST" not in board_html
        assert "LATEST" not in notice_html
        assert "자유게시판 고정글" in board_html
        assert "PINNED" in board_html
        assert "공지사항 전용 글" not in board_html
        assert "수정된 공지" in notice_html
        assert "자유게시판 고정글" not in notice_html

        unpinned = client.post(
            f"/board/{pinned_id}/pin",
            data={"csrf_token": "a" * 64, "is_pinned": "0"},
        )
        assert unpinned.status_code == 302

        deleted = client.post(
            f"/board/{owner_post_id}/delete",
            data={"csrf_token": "a" * 64},
        )
        assert deleted.status_code == 302
        assert client.get(f"/board/{owner_post_id}").status_code == 404

    connection = schema.connect(str(db_path))
    owner_row = connection.execute(
        "SELECT board_type, is_pinned FROM community_posts WHERE id=?", (owner_post_id,)
    ).fetchone()
    assert (owner_row["board_type"], owner_row["is_pinned"]) == ("community", 0)
    pinned_row = connection.execute(
        "SELECT board_type, is_pinned FROM community_posts WHERE id=?", (pinned_id,)
    ).fetchone()
    assert (pinned_row["board_type"], pinned_row["is_pinned"]) == ("community", 0)
    assert connection.execute(
        "SELECT board_type FROM community_posts WHERE id=?", (notice_id,)
    ).fetchone()["board_type"] == "notice"
    connection.close()


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
    assert "grid-template-columns: auto;" in badge_rule
    assert "grid-column: 1 / -1;" in source_rule
    template = (Path(__file__).parents[1] / "templates" / "companies.html").read_text(
        encoding="utf-8"
    )
    rating_badge = template.split('class="company-rating-badge"', 1)[1].split("</a>", 1)[0]
    assert "나이스신용평가 기준" not in rating_badge
    assert rating_badge.count("현재 신용등급") == 2  # aria-label and visible label
    assert 'class="rating-zero"' in template
    zero_rule = css.split(".company-rating-badge .rating-zero {", 1)[1].split("}", 1)[0]
    assert "font-size: 0.72em;" in zero_rule
    assert "font-weight: 400;" in zero_rule
    assert ".company-rating-badge .rating-zero::after" not in css


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
    assert "{% if executive.birth_date %}" in template
    assert "{% if company_research.ceo_names %}" in template
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


def test_board_templates_expose_admin_notice_and_owner_delete_controls():
    root = Path(__file__).parents[1]
    board_template = (root / "templates" / "community_board.html").read_text(
        encoding="utf-8"
    )
    post_template = (root / "templates" / "community_post.html").read_text(
        encoding="utf-8"
    )
    assert 'name="is_pinned"' in board_template
    assert "current_user_role == 'admin'" in board_template
    assert "post.is_pinned" in board_template
    assert "is_notice_board" in board_template
    assert "delete_community_post_route" in post_template
    assert "set_community_post_pinned_route" in post_template
    assert "상단 고정 해제" in post_template
    assert "current_user.id == post.author_id" in post_template


def test_community_table_keeps_metadata_columns_on_one_line():
    css = (Path(__file__).parents[1] / "static" / "css" / "dashboard.css").read_text(
        encoding="utf-8"
    )
    assert ".community-table{table-layout:fixed}" in css
    assert ".community-title-cell{width:auto;min-width:0}" in css
    assert ".community-table th:nth-child(4),.community-table td:nth-child(4){width:110px;white-space:nowrap}" in css
    assert ".community-table th:nth-child(5),.community-table td:nth-child(5){width:120px;white-space:nowrap}" in css
    assert "@media(max-width:760px){.community-table th:nth-child(n+3),.community-table td:nth-child(n+3){width:auto;white-space:normal}}" in css


def test_board_author_identity_is_avatar_only_and_flat():
    root = Path(__file__).parents[1]
    macro = (root / "templates" / "_membership_badge.html").read_text(
        encoding="utf-8"
    )
    community = (root / "templates" / "community_board.html").read_text(
        encoding="utf-8"
    )
    action_items = (root / "templates" / "action_items.html").read_text(
        encoding="utf-8"
    )
    css = (root / "static" / "css" / "dashboard.css").read_text(
        encoding="utf-8"
    )
    assert "is-compact is-board-author" in macro
    assert "{% if not compact %}<img class=\"membership-badge-icon\"" in macro
    assert "{% if not compact %}<span>{{ display_name or username" in macro
    assert ".member-identity.is-board-author .member-avatar-wrap:before" in css
    assert "display:none!important;content:none!important" in css
    assert ".member-identity.is-board-author .member-avatar{width:22px;height:22px" in css
    assert "<th>작성자</th>" not in community
    assert 'data-label="작성자"' not in community
    assert "<th>작성자</th>" not in action_items
    aura_css = (root / "static" / "css" / "profile-aura.css").read_text(
        encoding="utf-8"
    )
    assert "WebGL profile avatar" in aura_css
    assert ".member-identity.is-board-author .membership-badge-icon" in aura_css
    assert "display: none !important" in aura_css
    assert ".profile-avatar-webgl-canvas" in aura_css
    assert "profile-avatar-gold-orbit" not in aura_css
    assert ".community-table .community-author-cell::before" in aura_css
    base_template = (root / "templates" / "base.html").read_text(encoding="utf-8")
    assert "css/profile-aura.css" in base_template
    assert "js/profile-avatar-webgl.js" in base_template
    topbar_template = (root / "templates" / "_topbar.html").read_text(encoding="utf-8")
    account_template = (root / "templates" / "account.html").read_text(encoding="utf-8")
    assert topbar_template.count('data-profile-avatar-webgl="candidate"') == 2
    assert "account-avatar-wrap profile-avatar-webgl" in account_template
    webgl_js = (root / "static" / "js" / "profile-avatar-webgl.js").read_text(encoding="utf-8")
    for setting in (
        "animationSpeed", "ringThickness", "goldIntensity", "glowIntensity",
        "iridescenceIntensity", "refractionStrength", "sparkleIntensity",
        "pointerInfluence", "mobileQuality",
    ):
        assert setting in webgl_js
    assert "THREE.WebGLRenderer" in webgl_js
    assert "THREE.ShaderMaterial" in webgl_js
    assert "THREE.PlaneGeometry" in webgl_js
    assert "IntersectionObserver" in webgl_js
    assert 'document.addEventListener("visibilitychange"' in webgl_js
    assert "webglcontextlost" in webgl_js
    assert "webglcontextrestored" in webgl_js
    assert '.account-avatar-wrap[data-profile-avatar-webgl=' in webgl_js
    assert '.topbar-profile-menu[open] .topbar-profile-large-avatar' in webgl_js

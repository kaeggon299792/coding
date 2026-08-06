from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_primary_navigation_matches_confirmed_ia():
    markup = (ROOT / "templates" / "_topbar.html").read_text(encoding="utf-8")
    for label in (
        "홈", "뉴스", "시장 정보", "기업정보", "법률·규제", "자료실", "게시판",
        "통합검색", "회원정보관리", "관리자 전용",
    ):
        assert label in markup
    assert "파라디안 전용" not in markup
    assert ">데이터<" not in markup
    assert ">공시·재무<" not in markup
    assert ">기업 360°<" not in markup


def test_profile_popover_has_large_avatar_and_personal_greeting():
    markup = (ROOT / "templates" / "_topbar.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")
    assert 'class="topbar-profile-hero"' in markup
    assert 'class="topbar-profile-photo"' in markup
    assert "안녕하세요, {{ current_user.name or current_user.username }}님" in markup
    assert "topbar-profile-large-avatar" in markup
    assert ".topbar-profile-photo{" in css
    assert "width:76px;height:76px" in css


def test_mobile_navigation_and_company_filters_are_present():
    topbar = (ROOT / "templates" / "_topbar.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")
    company_news = (ROOT / "templates" / "company_news.html").read_text(encoding="utf-8")
    assert 'class="topbar-nav"' in topbar
    assert ".topbar-nav { display: flex" in css
    assert "overflow-x: auto" in css
    assert "white-space: nowrap" in css
    assert (
        "body.cinematic-home .topbar,body.cinematic-home .public-header"
        "{position:relative;z-index:60}" in css
    )
    assert 'class="company-news-filter"' in company_news
    for field in ("q", "company", "category", "importance", "analysis", "impact", "days"):
        assert f'name="{field}"' in company_news
    from services.company_intelligence import COMPANY_NEWS_CATEGORY_LABELS

    for category in ("경영·인사", "투자·시설", "재무·실적", "채용", "기타"):
        assert category in COMPANY_NEWS_CATEGORY_LABELS.values()


def test_english_catalog_and_sitemap_match_ia():
    import json

    catalog = json.loads(
        (ROOT / "translations" / "catalog.json").read_text(encoding="utf-8")
    )["text"]
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert catalog["시장 정보"] == "Market Intelligence"
    assert catalog["기업정보"] == "Company Intelligence"
    assert catalog["법률·규제"] == "Legal & Regulatory"
    assert catalog["자료실"] == "Resource Library"
    assert catalog["게시판"] == "Boards"
    for label in ("시장 정보", "기업정보", "법률·규제", "자료실", "게시판"):
        assert f'"label": "{label}"' in app_source


def test_canonical_routes_and_legacy_redirect_map_match_navigation():
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    for route in (
        '/news', '/news/overseas', '/market/casino-industry', '/market/stocks',
        '/companies/disclosures', '/companies/reports', '/companies/salary-ratings',
        '/companies/comparison', '/companies/expert',
        '/companies/recruitment', '/resources/source-data', '/board/bug-reports',
        '/laws', '/companies', '/search', '/sitemap',
    ):
        assert route in app_source
    for legacy_route in (
        '/performance/news', '/performance/overseas-news', '/disclosures',
        '/library', '/tips', '/bug-reports',
    ):
        assert legacy_route in app_source


def test_changed_templates_compile_in_flask():
    import app as app_module

    for template in (
        "_topbar.html", "_data_subnav.html", "public_home.html", "companies.html",
        "company_comparison.html", "company_expert.html",
        "disclosures.html", "company_news.html", "action_items.html",
        "action_item_detail.html", "laws.html", "account.html", "sitemap.html",
    ):
        app_module.app.jinja_env.get_template(template)


def test_page_loader_has_no_forced_completion_delay():
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "setTimeout(finish, 240)" not in base
    assert 'loader.classList.add("is-hidden")' in base


def test_market_sparklines_do_not_render_distorted_endpoint_circles():
    markup = (ROOT / "templates" / "market_trend.html").read_text(encoding="utf-8")
    assert "<circle" not in markup
    assert "final_point" not in markup

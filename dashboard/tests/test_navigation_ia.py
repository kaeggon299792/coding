from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_primary_navigation_matches_confirmed_ia():
    markup = (ROOT / "templates" / "_topbar.html").read_text(encoding="utf-8")
    for label in (
        "홈", "뉴스", "시장정보", "기업정보", "공시·리포트", "법률·규제", "자료실",
        "통합검색", "업무공간", "프로필", "관리자 페이지",
    ):
        assert label in markup
    assert "파라디안 전용" not in markup
    assert ">데이터<" not in markup
    assert ">공시·재무<" not in markup
    assert ">기업 360°<" not in markup


def test_mobile_navigation_and_company_filters_are_present():
    topbar = (ROOT / "templates" / "_topbar.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")
    companies = (ROOT / "templates" / "companies.html").read_text(encoding="utf-8")
    assert 'aria-controls="primary-navigation"' in topbar
    assert ".topbar-menu-toggle" in css
    assert "data-company-news-filters" in companies
    for category in ("경영·인사", "투자·시설", "재무·실적", "채용", "기타"):
        assert category in companies


def test_english_catalog_and_sitemap_match_ia():
    catalog = (ROOT / "translations" / "catalog.json").read_text(encoding="utf-8")
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    for label in (
        "Market Intelligence", "Company Intelligence", "Disclosures & Reports",
        "Legislative Trends", "Workspace", "Admin Console",
    ):
        assert label in catalog
    for label in ("시장정보", "기업정보", "공시·리포트", "업무공간"):
        assert f'"label": "{label}"' in app_source


def test_existing_urls_are_not_replaced_by_new_routes():
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    for route in (
        '/performance/news', '/performance/overseas-news', '/disclosures', '/laws',
        '/companies', '/library', '/search', '/sitemap',
    ):
        assert route in app_source


def test_changed_templates_compile_in_flask():
    import app as app_module

    for template in (
        "_topbar.html", "_data_subnav.html", "public_home.html", "companies.html",
        "disclosures.html", "laws.html", "account.html", "sitemap.html",
    ):
        app_module.app.jinja_env.get_template(template)

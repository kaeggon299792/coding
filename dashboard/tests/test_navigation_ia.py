from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_primary_navigation_matches_confirmed_ia():
    markup = (ROOT / "templates" / "_topbar.html").read_text(encoding="utf-8")
    for label in (
        "홈", "뉴스", "시장 정보", "기업정보", "법률·규제", "자료실", "게시판",
        "통합검색", "내 계정", "관리자 전용",
    ):
        assert label in markup
    assert "파라디안 전용" not in markup
    assert ">데이터<" not in markup
    assert ">공시·재무<" not in markup
    assert ">기업 360°<" not in markup


def test_mobile_navigation_and_company_filters_are_present():
    topbar = (ROOT / "templates" / "_topbar.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")
    company_news = (ROOT / "templates" / "company_news.html").read_text(encoding="utf-8")
    assert 'class="topbar-nav"' in topbar
    assert ".topbar-nav { display: flex" in css
    assert "overflow-x: auto" in css
    assert "white-space: nowrap" in css
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

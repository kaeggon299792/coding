import xml.etree.ElementTree as ET
import json
import re

import pytest
from werkzeug.security import generate_password_hash


@pytest.fixture
def client(monkeypatch, tmp_path):
    db_path = tmp_path / "seo_dashboard.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    monkeypatch.setattr(
        "services.market_data.fetch_global_quotes",
        lambda: {"quotes": [], "errors": []},
    )

    import app as app_module
    from dashboard_db import queries
    from extensions import dashboard_db

    connection = dashboard_db()
    queries.create_user(
        connection,
        "admin",
        generate_password_hash("correct-horse-battery-staple"),
    )
    connection.execute(
        """
        INSERT INTO tips_articles (
            id, slug, title, summary, body, category, tags_json,
            published_date, updated_date, reading_time, featured, draft,
            cover_image, author_id, view_count, is_deleted, deleted_at,
            deleted_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "tip-seo-1",
            "seo-test-tip",
            "SEO 테스트 자료",
            "검색엔진 최적화 테스트용 공개 자료입니다.",
            "카지노 산업 SEO 점검을 위한 공개 테스트 글입니다.",
            "데이터 분석",
            "[]",
            "2026-07-31",
            "2026-07-31",
            None,
            0,
            0,
            None,
            1,
            0,
            0,
            None,
            None,
            "2026-07-31T09:00:00+09:00",
            "2026-07-31T09:30:00+09:00",
        ),
    )
    connection.commit()
    connection.close()

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def test_home_has_canonical_meta_and_structured_data(client):
    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "<title>Casino IN | 카지노 산업 정보와 인사이트</title>" in html
    assert (
        'content="국내외 카지노 기업, 관광객, 환율, 공시, 시장 동향과 산업 데이터를 한곳에서 확인하는 카지노 산업 인텔리전스 플랫폼입니다."'
        in html
    )
    assert 'rel="canonical" href="https://www.casinoin.kr/"' in html
    assert 'property="og:url" content="https://www.casinoin.kr/"' in html
    assert 'name="twitter:card" content="summary_large_image"' in html
    assert '"@type": "WebSite"' in html
    assert '"@type": "SearchAction"' in html
    assert '"@type": "BreadcrumbList"' in html


def test_unified_search_is_noindex(client):
    response = client.get("/search")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'name="robots" content="noindex,nofollow"' in html


def test_error_page_is_noindex(client):
    response = client.get("/does-not-exist")
    html = response.get_data(as_text=True)

    assert response.status_code == 404
    assert 'name="robots" content="noindex,nofollow"' in html


def test_robots_txt(client):
    response = client.get("/robots.txt")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "text/plain" in response.content_type
    assert "Disallow: /official-docs/" in body
    assert "Disallow: /en/official-docs/" in body
    assert "Disallow: /ja/official-docs/" in body
    assert "Disallow: /yue-hk/official-docs/" in body
    assert "Disallow: /admin" in body
    assert "Sitemap: https://www.casinoin.kr/sitemap.xml" in body
    assert "\nDisallow: /\n" not in f"\n{body}\n"


def test_sitemap_xml(client):
    response = client.get("/sitemap.xml")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "application/xml" in response.content_type
    assert "<urlset" in body
    assert "https://www.casinoin.kr/" in body
    assert "https://www.casinoin.kr/en/" in body
    assert "https://www.casinoin.kr/resources/seo-test-tip" in body
    assert "https://www.casinoin.kr/en/resources/seo-test-tip" in body
    assert "/search" not in body
    assert "/board/bug-reports" not in body
    assert "casino.shingoon.me" not in body
    assert "/performance/" not in body
    assert "/tips/" not in body

    root = ET.fromstring(response.data)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [node.text for node in root.findall("sm:url/sm:loc", ns)]
    assert "https://www.casinoin.kr/" in urls
    assert "https://www.casinoin.kr/ja/" in urls
    assert "https://www.casinoin.kr/yue-hk/" in urls


def test_every_static_indexable_page_has_locale_specific_search_copy():
    import app as app_module

    static_endpoints = app_module.INDEXABLE_ENDPOINTS - {"tips.detail_page"}
    for locale in ("ko", "en", "ja", "yue-HK"):
        missing = static_endpoints - set(app_module.SEO_PAGE_COPY[locale])
        assert not missing, f"{locale} SEO copy missing: {sorted(missing)}"
        descriptions = [
            app_module.SEO_PAGE_COPY[locale][endpoint][1]
            for endpoint in static_endpoints
        ]
        assert len(descriptions) == len(set(descriptions))


def test_japanese_and_cantonese_pages_explain_their_content(client):
    japanese = client.get("/ja/companies")
    japanese_html = japanese.get_data(as_text=True)
    assert japanese.status_code == 200
    assert "<title>韓国カジノ企業の比較分析 | Casino IN</title>" in japanese_html
    assert "パラダイス、GKL、カンウォンランド" in japanese_html
    assert 'property="og:locale" content="ja_JP"' in japanese_html
    assert '"inLanguage": "ja-JP"' in japanese_html
    assert '"@type": "WebPage"' in japanese_html

    cantonese = client.get("/yue-hk/companies/benefits")
    cantonese_html = cantonese.get_data(as_text=True)
    assert cantonese.status_code == 200
    assert "<title>賭場企業員工福利比較｜Casino IN</title>" in cantonese_html
    assert "津貼金額或水平" in cantonese_html
    assert 'property="og:locale" content="yue_HK"' in cantonese_html
    assert '"inLanguage": "yue-HK"' in cantonese_html


def test_indexable_section_has_webpage_structured_data(client):
    response = client.get("/market/casino-industry")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '"@type": "WebPage"' in html
    payloads = [
        json.loads(payload)
        for payload in re.findall(
            r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL
        )
    ]
    webpage = next(item for item in payloads if item.get("@type") == "WebPage")
    assert webpage["description"].startswith("국내 외국인전용 카지노 사업장 현황")


def test_old_dashboard_host_redirects_to_canonical_domain(client):
    response = client.get(
        "/performance/news?ref=legacy",
        base_url="http://dashboard.shingoon.me",
        follow_redirects=False,
    )

    assert response.status_code == 301
    assert (
        response.headers["Location"]
        == "https://www.casinoin.kr/news?ref=legacy"
    )
    csp = response.headers["Content-Security-Policy"]
    assert re.search(r"script-src 'self' 'nonce-[A-Za-z0-9_-]+'", csp)
    assert "'nonce-' " not in csp


@pytest.mark.parametrize(
    ("legacy_path", "canonical_path"),
    (
        ("/performance/news", "/news"),
        ("/performance/overseas-news", "/news/overseas"),
        ("/performance/casino-industry/visitors", "/market/casino-industry/visitors"),
        ("/performance/markets", "/market/stocks"),
        ("/performance/tourism", "/market/tourism"),
        ("/performance/economy", "/market/exchange-rates-and-oil"),
        ("/performance/holidays", "/market/holidays"),
        ("/performance/salaries", "/companies/salary-ratings"),
        ("/performance/recruitment", "/companies/recruitment"),
        ("/disclosures", "/companies/disclosures"),
        ("/disclosures/ir/42/download", "/companies/disclosures/ir/42/download"),
        ("/library", "/companies/reports"),
        ("/library/42/download", "/companies/reports/42/download"),
        ("/tips", "/resources"),
        ("/tips/example", "/resources/example"),
        ("/performance/source-download", "/resources/source-data"),
        ("/bug-reports/42", "/board/bug-reports/42"),
        ("/paradian", "/admin"),
    ),
)
def test_legacy_paths_redirect_once_to_final_canonical_url(
    client, legacy_path, canonical_path
):
    response = client.get(
        f"{legacy_path}?view=all", base_url="https://www.casinoin.kr",
        follow_redirects=False,
    )

    assert response.status_code == 301
    assert response.headers["Location"] == (
        f"https://www.casinoin.kr{canonical_path}?view=all"
    )


def test_domain_scheme_locale_query_and_trailing_slash_redirects_are_canonical(client):
    cases = (
        (
            "/companies?tab=news", "https://casinoin.kr",
            "https://www.casinoin.kr/companies?tab=news",
        ),
        (
            "/companies?tab=news", "https://casino.shingoon.me",
            "https://www.casinoin.kr/companies?tab=news",
        ),
        (
            "/companies", "http://www.casinoin.kr",
            "https://www.casinoin.kr/companies",
        ),
        (
            "/ja/performance/holidays/?year=2027", "https://casino.shingoon.me",
            "https://www.casinoin.kr/ja/market/holidays?year=2027",
        ),
        (
            "/news/", "https://www.casinoin.kr",
            "https://www.casinoin.kr/news",
        ),
    )
    for path, base_url, expected in cases:
        response = client.get(path, base_url=base_url, follow_redirects=False)
        assert response.status_code == 301
        assert response.headers["Location"] == expected


def test_untrusted_host_is_rejected_before_legacy_redirect(client, monkeypatch):
    monkeypatch.setitem(client.application.config, "TESTING", False)
    response = client.get(
        "/performance/news", base_url="https://attacker.example",
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "Location" not in response.headers


@pytest.mark.parametrize(
    "path",
    (
        "/news",
        "/news/overseas",
        "/market/casino-industry",
        "/market/stocks",
        "/companies",
        "/companies/benefits",
        "/companies/news",
        "/companies/disclosures",
        "/companies/reports",
        "/companies/salary-ratings",
        "/companies/recruitment",
        "/companies/recruitment-guide",
        "/resources",
        "/resources/sites",
        "/resources/glossary",
        "/board",
        "/board/notices",
    ),
)
def test_canonical_public_routes_return_content_without_redirect(client, path):
    response = client.get(path, base_url="https://www.casinoin.kr", follow_redirects=False)
    assert response.status_code == 200
    assert 'rel="canonical" href="https://www.casinoin.kr' in response.get_data(as_text=True)


def test_tip_detail_uses_article_meta(client):
    response = client.get("/resources/seo-test-tip")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "<title>SEO 테스트 자료 | Casino IN</title>" in html
    assert 'property="og:type" content="article"' in html
    assert '"@type": "Article"' in html
    assert '"@type": "BreadcrumbList"' in html

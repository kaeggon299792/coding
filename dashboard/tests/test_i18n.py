import re

import pytest
from werkzeug.security import generate_password_hash

from localization import locale_for_country, translate_source_label


def test_country_locale_mapping():
    assert locale_for_country("KR") == "ko"
    assert locale_for_country("JP") == "ja"
    assert locale_for_country("CN") == "yue-HK"
    assert locale_for_country("HK") == "yue-HK"
    assert locale_for_country("MO") == "yue-HK"
    assert locale_for_country("US") == "en"
    assert locale_for_country("XX") is None


def test_source_series_compound_labels_translate_korean_frequency_tokens():
    source = "GKL - Busan Lotte Casino - 전체 입장객 (연누계·2026년 7월 기준)"
    assert translate_source_label(source, "en") == (
        "GKL - Busan Lotte Casino - Total visitors "
        "(Year-to-date·As of July 2026)"
    )
    assert "연누계" not in translate_source_label(source, "ja")
    assert "입장객" not in translate_source_label(source, "yue-HK")
    assert translate_source_label("월별 데이터 표", "ja") == "月別 データ表"


@pytest.fixture
def client(monkeypatch, tmp_path):
    db_path = tmp_path / "i18n_dashboard.db"
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
    connection.execute("UPDATE dashboard_users SET role='admin' WHERE username='admin'")
    connection.commit()
    connection.close()

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def _csrf(response):
    match = re.search(
        r'name="csrf_token" value="([a-f0-9]+)"',
        response.get_data(as_text=True),
    )
    return match.group(1)


def test_korean_home_remains_default(client):
    response = client.get("/")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert response.headers["Content-Language"] == "ko"
    assert '<html lang="ko"' in html
    assert 'class="public-hero-art-image"' in html
    assert "DATA" not in html
    assert 'href="/en/" data-locale-link="en"' in html
    assert 'href="/ja/" data-locale-link="ja"' in html
    assert 'href="/yue-hk/" data-locale-link="yue-HK"' in html
    assert 'id="dashboard-i18n-catalog"' not in html
    assert "dashboard-i18n.js" not in html
    pairs = (
        ("카지노인을 위한 모든 정보.", "Everything casino professionals need."),
        ("카지노인을 위한 하나의 공간.", "One space for the casino industry."),
        ("카지노 업계를 한눈에.", "The casino industry at a glance."),
        ("필요한 정보를, 필요한 순간에.", "The right information, right when you need it."),
        ("업계의 흐름을 가장 빠르게.", "Stay ahead of the industry."),
        ("정보는 흩어져 있어도, 인사이트는 하나로.", "Scattered information. Connected insight."),
        ("카지노 산업을 더 가까이.", "Bringing the casino industry closer."),
    )
    assert any(korean in html and english in html for korean, english in pairs)


@pytest.mark.parametrize(
    ("country", "location", "cookie_value"),
    (
        ("JP", "/ja/", "ja"),
        ("CN", "/yue-hk/", "yue-HK"),
        ("MO", "/yue-hk/", "yue-HK"),
        ("US", "/en/", "en"),
    ),
)
def test_first_visit_country_redirects_to_localized_home(
    client, country, location, cookie_value
):
    response = client.get(
        "/", headers={"CF-IPCountry": country}, follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith(location)
    assert f"casino_locale={cookie_value}" in response.headers["Set-Cookie"]


def test_saved_locale_overrides_country_detection(client):
    client.set_cookie("casino_locale", "ko")
    response = client.get(
        "/", headers={"CF-IPCountry": "JP"}, follow_redirects=False
    )
    assert response.status_code == 200


def test_english_home_uses_same_route_with_localized_seo(client):
    response = client.get("/en/")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert response.headers["Content-Language"] == "en"
    assert '<html lang="en"' in html
    assert "Casino Industry Information and Insights" in html
    assert ">Market Intelligence<" in html
    assert 'rel="canonical" href="https://www.casinoin.kr/en/"' in html
    assert 'hreflang="ko" href="https://www.casinoin.kr/"' in html
    assert 'hreflang="en" href="https://www.casinoin.kr/en/"' in html
    assert 'hreflang="x-default"' in html
    assert "G-PTRL0XC53Z" in html
    assert 'id="dashboard-i18n-catalog"' in html
    assert "dashboard-i18n.js" in html
    taglines = {
        "Everything casino professionals need.",
        "One space for the casino industry.",
        "The casino industry at a glance.",
        "The right information, right when you need it.",
        "Stay ahead of the industry.",
        "Scattered information. Connected insight.",
        "Bringing the casino industry closer.",
    }
    assert any(tagline in html for tagline in taglines)
    assert 'Created by Woojin Shin' in html
    assert '신우진 제작' not in html
    assert "Created by 신우진" not in html


@pytest.mark.parametrize(
    "path",
    (
        "/en/market/casino-industry",
        "/en/news",
        "/en/market/stocks",
        "/en/market/tourism",
        "/en/market/exchange-rates-and-oil",
        "/en/market/holidays",
        "/en/companies/salary-ratings",
        "/en/companies/recruitment",
        "/en/companies/disclosures",
        "/en/laws",
        "/en/companies",
        "/en/companies/reports",
        "/en/search",
        "/en/credits",
        "/en/resources",
        "/en/board/bug-reports",
    ),
)
def test_public_english_routes_keep_endpoint_parity(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 200
    assert response.headers["Content-Language"] == "en"
    assert '<html lang="en"' in response.get_data(as_text=True)


def test_language_switch_preserves_path_and_query(client):
    response = client.get("/en/market/holidays?year=2027")
    html = response.get_data(as_text=True)
    assert 'href="/market/holidays?year=2027" data-locale-link="ko"' in html
    assert (
        'href="/en/market/holidays?year=2027" data-locale-link="en"'
        in html
    )
    assert 'href="/ja/market/holidays?year=2027" data-locale-link="ja"' in html
    assert 'href="/yue-hk/market/holidays?year=2027" data-locale-link="yue-HK"' in html


@pytest.mark.parametrize("locale", ("ja", "yue-hk"))
def test_additional_locale_prefixes_use_same_routes(client, locale):
    response = client.get(f"/{locale}/news")
    assert response.status_code == 200
    expected = "yue-HK" if locale == "yue-hk" else locale
    assert response.headers["Content-Language"] == expected
    html = response.get_data(as_text=True)
    assert f'<html lang="{expected}"' in html
    assert 'id="dashboard-i18n-catalog"' not in html
    assert "dashboard-i18n.js" not in html


def test_english_static_assets_are_served_through_prefix(client):
    response = client.get("/en/static/js/dashboard-i18n.js")
    assert response.status_code == 200
    assert b"DashboardI18n" in response.data


def test_english_library_explains_upload_title_priority(client):
    with client.session_transaction() as session:
        session["user_id"] = 1
        session["username"] = "admin"
        session["role"] = "admin"

    response = client.get("/en/companies/reports")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'placeholder="Leave blank to let GPT generate the title."' in html
    assert "A title you enter takes highest priority." in html
    assert "if GPT provides no title or AI analysis fails" in html


def test_protected_english_page_redirects_to_english_login(client):
    response = client.get("/en/official-docs/", follow_redirects=False)
    assert response.status_code == 302
    assert "/en/login?next=/en/official-docs/" in response.headers["Location"]


def test_english_login_post_keeps_prefix_and_rejects_external_next(client):
    login_page = client.get("/en/login?next=/en/official-docs/")
    html = login_page.get_data(as_text=True)
    assert 'action="/en/login?next=/en/official-docs/"' in html
    assert (
        'href="/login?next=%2Fofficial-docs%2F" data-locale-link="ko"'
        in html
    )
    token = _csrf(login_page)
    response = client.post(
        "/en/login?next=https://example.com/phishing",
        data={
            "username": "admin",
            "password": "correct-horse-battery-staple",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/en/dashboard")


def test_unknown_english_url_uses_localized_error_page(client):
    response = client.get("/en/not-a-real-page")
    html = response.get_data(as_text=True)
    assert response.status_code == 404
    assert '<html lang="en"' in html
    assert "Page not found" in html
    assert "/en/sitemap" in html


def test_english_credits_page_shows_site_guide(client):
    response = client.get("/en/credits")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<html lang="en"' in html
    assert "Site Guide" in html
    assert "Silver" in html and "Black" in html


def test_dynamic_translation_patterns_expand_capture_groups():
    from localization import translate_text

    translated = translate_text(
        "아이디 또는 비밀번호가 올바르지 않습니다. 차단까지 9회 남았습니다.",
        "en",
    )
    assert (
        translated
        == "Incorrect username or password. "
        "9 attempts remain before this IP address is blocked."
    )


def test_visible_dynamic_korean_is_discovered_without_scripts_or_code():
    from localization import extract_translatable_html_strings

    html = """
    <article aria-label="파라다이스 기업 카드">
      <h2>파라다이스</h2><li>외국인 관광객 회복</li>
      <code>비밀 한국어</code><script>const message = '실행 한국어';</script>
    </article>
    """
    assert extract_translatable_html_strings(html) == [
        "파라다이스 기업 카드", "파라다이스", "외국인 관광객 회복",
    ]


def test_changing_korean_financial_and_people_units_translate_without_exact_entries():
    from localization import translate_text

    assert translate_text("11,499억원", "en") == "KRW 1,149.9B"
    assert translate_text("3,450만원", "en") == "KRW 34.50M"
    assert translate_text("+1,883,952명", "en") == "+1,883,952 people"

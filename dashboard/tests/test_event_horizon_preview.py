from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(tmp_path / "event_horizon_test.db"))
    import app as app_module

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def test_event_horizon_preview_is_public_and_noindex(client):
    response = client.get("/test/event-horizon")

    assert response.status_code == 200
    assert b"<title>Event Horizon Hero Preview | Casino IN</title>" in response.data
    assert b'id="event-horizon-title">CASINO IN' in response.data
    assert b'content="noindex,nofollow"' in response.data
    assert "frame-src 'self' https://www.googletagmanager.com" in response.headers[
        "Content-Security-Policy"
    ]

    asset = client.get("/static/hero-effects/event-horizon.html")
    assert asset.status_code == 200
    assert "script-src 'self' 'unsafe-inline'" in asset.headers["Content-Security-Policy"]
    assert "frame-ancestors 'self'" in asset.headers["Content-Security-Policy"]
    assert asset.headers["X-Frame-Options"] == "SAMEORIGIN"


def test_event_horizon_preview_uses_real_routes_and_local_asset(client):
    page = client.get("/test/event-horizon").get_data(as_text=True)

    assert 'href="/market/casino-industry"' in page
    assert 'href="/companies"' in page
    assert 'data-effect-src="/static/hero-effects/event-horizon.html?v=20260807-1"' in page
    assert 'href="/static/css/event-horizon-hero.css?v=20260808-home4"' in page
    assert 'src="/static/js/event-horizon-hero.js?v=20260808-fullbleed4"' in page


def test_event_horizon_assets_preserve_fonts_and_original_shader_features():
    template = (ROOT / "templates" / "test_event_horizon.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "event-horizon-hero.css").read_text(encoding="utf-8")
    javascript = (ROOT / "static" / "js" / "event-horizon-hero.js").read_text(encoding="utf-8")
    shader = (ROOT / "static" / "hero-effects" / "event-horizon.html").read_text(encoding="utf-8")

    combined = "\n".join((template, css, javascript))
    assert "font-family" not in combined
    assert "@font-face" not in combined
    assert "DM Sans" not in combined
    assert "three" not in javascript.lower()
    assert "const float RS = 1.0" in shader
    assert "Novikov-Thorne" in shader
    assert "Velocity-Verlet" in shader
    assert "starField" in shader
    assert "Doppler beaming" in shader
    assert "for (int i = 0; i < 200; i++)" in shader
    assert "IntersectionObserver" in javascript
    assert 'document.addEventListener("visibilitychange"' in javascript
    assert "destroyEventHorizonHero" in javascript
    assert "webglcontextlost" in shader
    assert "webglcontextrestored" in shader
    assert "prefers-reduced-motion: reduce" in shader
    assert "Math.min(window.devicePixelRatio || 1, 1.5)" in shader


def test_homepage_exposes_lazy_random_hero_candidates(client):
    response = client.get("/")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'data-home-hero-template="spotlight"' in page
    assert 'data-home-hero-template="event-horizon"' in page
    assert 'src="/static/js/home-hero-loader.js?v=20260808-random-hero3"' in page
    assert "data-home-sitemap" not in page
    assert page.count("시장정보 보기") >= 2
    assert page.count("기업정보 보기") >= 2
    assert '<script src="/static/js/event-horizon-hero.js' not in page
    assert re.search(
        r'<script[^>]+src="/static/vendor/three/three\.r149\.min\.js"', page
    ) is None
    assert re.search(
        r'<script[^>]+src="/static/js/casino-wave-webgl-v2\.js', page
    ) is None
    assert '<iframe class="event-horizon-frame"' not in page
    assert "Event Horizon Hero Preview" not in page
    assert "frame-src 'self' https://www.googletagmanager.com" in response.headers[
        "Content-Security-Policy"
    ]


def test_random_home_hero_loads_only_the_selected_effect_assets():
    partial = (ROOT / "templates" / "_home_hero_random.html").read_text(encoding="utf-8")
    loader = (ROOT / "static" / "js" / "home-hero-loader.js").read_text(encoding="utf-8")
    event_horizon_css = (ROOT / "static" / "css" / "event-horizon-hero.css").read_text(
        encoding="utf-8"
    )
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")

    assert 'sessionStorage.getItem(key)' in partial
    assert 'sessionStorage.setItem(key, selected)' in partial
    assert '"casino-in-home-hero-v1"' in partial
    assert 'stylesheet.dataset.homeHeroAsset = selected' in partial
    assert 'selected === "event-horizon"' in loader
    assert "data-home-sitemap" not in loader
    assert 'loadScript(slot.dataset.eventHorizonSrc)' in loader
    assert 'loadScript(slot.dataset.threeSrc)' in loader
    assert '.then(() => loadScript(slot.dataset.waveSrc))' in loader
    assert "event-horizon-hero.css') }}?v=20260808-home4" in partial
    assert 'html[data-home-hero="event-horizon"] .home-hero-slot::before' in event_horizon_css
    assert (
        'html[data-home-hero="event-horizon"] .page-container > .home-hero-slot::before'
        in event_horizon_css
    )
    assert "top: calc(-1 * var(--space-6));" in event_horizon_css
    assert "top: calc(-1 * var(--space-4));" in event_horizon_css
    assert "width: 100vw;" in event_horizon_css
    assert "margin-inline: calc(50% - 50vw);" in event_horizon_css
    assert "max-width: 1440px;" in event_horizon_css
    assert 'name: "BH_CENTER_X", value: mobile ? 0.5 : 0.69' in (
        ROOT / "static" / "js" / "event-horizon-hero.js"
    ).read_text(encoding="utf-8")
    assert 'name: "BH_SCALE", value: mobile ? 0.72 : 1.08' in (
        ROOT / "static" / "js" / "event-horizon-hero.js"
    ).read_text(encoding="utf-8")
    assert "casino-wave-webgl.css" not in base
    assert "three.r149.min.js" not in base
    assert "casino-wave-webgl-v2.js" not in base

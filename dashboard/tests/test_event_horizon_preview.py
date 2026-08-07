from pathlib import Path

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
    assert 'src="/static/js/event-horizon-hero.js?v=20260807-1"' in page


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


def test_homepage_does_not_load_event_horizon_preview(client):
    page = client.get("/").get_data(as_text=True)

    assert "event-horizon-hero.js" not in page
    assert "hero-effects/event-horizon.html" not in page
    assert "Event Horizon Hero Preview" not in page

import pytest


@pytest.fixture
def client(monkeypatch, tmp_path):
    db_path = tmp_path / "blackhole_showcase.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))

    import app as app_module

    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def test_showcase_page_is_public_and_renders_canvas(client):
    response = client.get("/showcase/black-hole")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'data-blackhole-hero' in html
    assert 'data-blackhole-canvas' in html
    assert 'js/blackhole-hero-renderer.js' in html
    assert 'css/blackhole-hero.css' in html
    assert 'BlackHoleHeroRenderer' in html


def test_showcase_page_is_noindex(client):
    html = client.get("/showcase/black-hole").get_data(as_text=True)
    assert 'name="robots" content="noindex,nofollow"' in html


def test_showcase_page_excluded_from_sitemap(client):
    xml = client.get("/sitemap.xml").get_data(as_text=True)
    assert "/showcase/black-hole" not in xml


def test_showcase_page_ships_csp_nonce_on_its_scripts(client):
    response = client.get("/showcase/black-hole")
    html = response.get_data(as_text=True)
    csp = response.headers.get("Content-Security-Policy", "")
    nonce = None
    for part in csp.split(";"):
        part = part.strip()
        if part.startswith("script-src "):
            for token in part.split():
                if token.startswith("'nonce-"):
                    nonce = token.strip("'").split("nonce-", 1)[1]
    assert nonce, "script-src nonce missing from CSP header"
    assert f'nonce="{nonce}"' in html


def test_showcase_renderer_exposes_matching_default_options():
    from pathlib import Path

    js = Path(__file__).resolve().parent.parent.joinpath(
        "static", "js", "blackhole-hero-renderer.js"
    ).read_text(encoding="utf-8")
    for shader_name in (
        "VERT", "SCENE_FRAG", "BLEND_FRAG", "BRIGHT_FRAG", "BLUR_FRAG", "COMPOSITE_FRAG",
    ):
        assert f"const {shader_name} = `" in js
    for uniform in (
        "uCamPos", "uTanHalf", "uDiskIn", "uDiskOut", "uThick", "uSpin",
        "uDoppler", "uHot", "uMid", "uCool", "uStars", "uJitter", "uSeed",
    ):
        assert uniform in js
    for option_key in (
        "distance: 24", "elevation: -5.5", "fov: 42", "diskInner: 3",
        "diskOuter: 15", "spinSpeed: 0.06", "doppler: 0.35",
        "hotColor: \"#FFF3DE\"", "midColor: \"#FF9838\"", "coolColor: \"#8E3A0B\"",
        "steps: 300", "resolution: 0.7", "maxDpr: 1.75",
    ):
        assert option_key in js

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(tmp_path / "mesh_gradient_test.db"))
    import app as app_module

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def test_mesh_gradient_preview_is_public_noindex_and_uses_real_routes(client):
    response = client.get("/test/mesh-gradient-hero")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Mesh Gradient Hero Preview | Casino IN" in page
    assert 'content="noindex,nofollow"' in page
    assert 'id="mesh-gradient-hero"' in page
    assert 'href="/market/casino-industry"' in page
    assert 'href="/companies"' in page
    assert 'data-ui-icon="arrow-right"' in page
    assert "https://cdn.jsdelivr.net" in response.headers["Content-Security-Policy"]


def test_mesh_gradient_preview_uses_pinned_official_vanilla_shader_only():
    javascript = (ROOT / "static" / "js" / "mesh-gradient-hero.js").read_text(
        encoding="utf-8"
    )
    template = (ROOT / "templates" / "test_mesh_gradient_hero.html").read_text(
        encoding="utf-8"
    )

    assert 'PAPER_SHADER_VERSION = "0.0.78"' in javascript
    assert "@paper-design/shaders@${PAPER_SHADER_VERSION}/dist" in javascript
    assert 'import(`${PAPER_SHADER_BASE}/shader-mount.js`)' in javascript
    assert 'import(`${PAPER_SHADER_BASE}/shaders/mesh-gradient.js`)' in javascript
    assert "meshGradientFragmentShader" in javascript
    assert "new modules.ShaderMount" in javascript
    assert javascript.count("new modules.ShaderMount") == 2
    assert 'PRIMARY_COLORS = ["#000000", "#1a1a1a", "#2e2e2e", "#ffffff"]' in javascript
    assert 'SECONDARY_COLORS = ["#000000", "#ffffff", "#2e2e2e"]' in javascript
    assert "reducedMotion ? 0 : 0.25" in javascript
    assert "reducedMotion ? 0 : 0.15" in javascript
    assert "@paper-design/shaders-react" not in javascript
    assert "react" not in template.lower()
    assert "framer" not in template.lower()
    assert "three" not in javascript.lower()


def test_mesh_gradient_preview_preserves_fonts_and_has_fallback_lifecycle():
    template = (ROOT / "templates" / "test_mesh_gradient_hero.html").read_text(
        encoding="utf-8"
    )
    css = (ROOT / "static" / "css" / "mesh-gradient-hero.css").read_text(
        encoding="utf-8"
    )
    javascript = (ROOT / "static" / "js" / "mesh-gradient-hero.js").read_text(
        encoding="utf-8"
    )
    combined = "\n".join((template, css, javascript))

    assert "font-family" not in combined
    assert "@font-face" not in combined
    assert "DM Sans" not in combined
    assert "initMeshGradientHero" in javascript
    assert "destroyMeshGradientHero" in javascript
    assert "IntersectionObserver" not in javascript
    assert 'window.addEventListener("pagehide"' in javascript
    assert 'window.matchMedia("(prefers-reduced-motion: reduce)")' in javascript
    assert 'get("webgl") === "off"' in javascript
    assert 'fallback("forced-fallback")' in javascript
    assert 'mount.canvasElement.addEventListener("webglcontextlost"' in javascript
    assert ".mesh-gradient-hero.is-shader-fallback" in css
    assert ".mesh-gradient-layer-secondary" in css
    assert "opacity: 0.4;" in css


def test_homepage_registers_mesh_gradient_without_eager_script_or_stylesheet(client):
    page = client.get("/").get_data(as_text=True)

    assert 'data-home-hero-template="mesh-gradient"' in page
    assert '<script type="module" src="/static/js/mesh-gradient-hero.js' not in page
    assert '<link rel="stylesheet" href="/static/css/mesh-gradient-hero.css' not in page
    assert "@paper-design/shaders" not in page


def test_home_loader_keeps_three_candidates_but_initializes_only_the_selection():
    config = (ROOT / "config.py").read_text(encoding="utf-8")
    loader = (ROOT / "static" / "js" / "home-hero-loader.js").read_text(encoding="utf-8")

    assert '{"value": "spotlight", "label": "DOT"}' in config
    assert '{"value": "event-horizon", "label": "Event Horizon"}' in config
    assert '{"value": "mesh-gradient", "label": "Mesh Gradient"}' in config
    assert 'const allowed = ["spotlight", "event-horizon", "mesh-gradient"]' in loader
    assert 'if (selected === "mesh-gradient")' in loader
    assert 'if (selected === "event-horizon")' in loader


def test_home_dot_is_one_theme_aware_original_and_mesh_matches_preview_copy():
    dot = (ROOT / "templates" / "_hero_spotlight.html").read_text(encoding="utf-8")
    mesh = (ROOT / "templates" / "_hero_mesh_gradient.html").read_text(encoding="utf-8")
    preview = (ROOT / "templates" / "test_mesh_gradient_hero.html").read_text(encoding="utf-8")

    assert "public-hero-wordmark-dark" in dot
    assert "public-hero-wordmark-light" in dot
    assert "public-hero-actions" not in dot
    assert "CASINO INDUSTRY INTELLIGENCE" in mesh
    assert "산업의 흐름을" in mesh and "한발 먼저 읽다" in mesh
    assert "CASINO INDUSTRY INTELLIGENCE" in preview
    assert "산업의 흐름을" in preview and "한발 먼저 읽다" in preview

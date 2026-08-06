from __future__ import annotations

import json
from pathlib import Path

from services.vite_assets import vite_entry_assets


ROOT = Path(__file__).resolve().parents[1]


def test_blackhole_vite_manifest_resolves_hashed_local_assets():
    assets = vite_entry_assets("blackhole-hero")
    assert assets["available"] is True
    assert assets["js"].startswith("blackhole-hero/assets/main-")
    assert assets["js"].endswith(".js")
    assert all(value.startswith("blackhole-hero/assets/main-") for value in assets["css"])
    assert (ROOT / "static" / assets["js"]).is_file()
    assert all((ROOT / "static" / value).is_file() for value in assets["css"])


def test_blackhole_vite_manifest_fails_closed_for_missing_bundle():
    assets = vite_entry_assets("bundle-that-does-not-exist")
    assert assets == {"available": False, "js": "", "css": []}
    assert vite_entry_assets("../outside") == assets


def test_profile_island_uses_original_raw_webgl_pipeline():
    component = (
        ROOT
        / "frontend"
        / "blackhole-hero"
        / "src"
        / "components"
        / "ui"
        / "blackhole-hero-section.tsx"
    ).read_text(encoding="utf-8")
    for marker in (
        "SCENE_FRAG",
        "BLEND_FRAG",
        "BRIGHT_FRAG",
        "BLUR_FRAG",
        "COMPOSITE_FRAG",
        "MAX_STEPS 460",
        "vec3 acc=-1.5*h2*pos",
        "uDoppler",
        "uJitter",
        "WebGL2RenderingContext",
        "IntersectionObserver",
        "visibilitychange",
        "webglcontextlost",
        "webglcontextrestored",
        "premultipliedAlpha:false",
        "uTransparent",
        "frontComposite",
        "frontContext.drawImage",
    ):
        assert marker in component
    assert "THREE" not in component
    assert "radial-gradient" not in component


def test_profile_island_is_bounded_to_existing_account_avatar_layout():
    topbar = (ROOT / "templates" / "_topbar.html").read_text(encoding="utf-8")
    account = (ROOT / "templates" / "account.html").read_text(encoding="utf-8")
    styles = (
        ROOT / "frontend" / "blackhole-hero" / "src" / "styles.css"
    ).read_text(encoding="utf-8")
    assert 'id="blackhole-avatar-root"' in topbar
    assert 'data-blackhole-avatar-fallback' in topbar
    assert 'id="blackhole-profile-root"' not in account
    assert "width: 196px" in styles
    assert "height: 154px" in styles
    assert "background: transparent" in styles
    assert "blackhole-renderer-front-canvas" in styles


def test_profile_island_build_is_self_hosted_and_manifested():
    manifest = json.loads(
        (ROOT / "static" / "blackhole-hero" / "manifest.json").read_text(encoding="utf-8")
    )
    entry = manifest["src/main.tsx"]
    assert entry["isEntry"] is True
    assert not entry["file"].startswith(("http://", "https://"))
    package = json.loads(
        (ROOT / "frontend" / "blackhole-hero" / "package.json").read_text(encoding="utf-8")
    )
    assert package["dependencies"] == {
        "react": "^19.1.1",
        "react-dom": "^19.1.1",
    }

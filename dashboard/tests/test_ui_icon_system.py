from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_local_lucide_style_icon_system_is_loaded_without_framework_or_cdn():
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    icons = (ROOT / "static" / "js" / "ui-icons.js").read_text(encoding="utf-8")

    assert "js/ui-icons.js" in base
    assert "lucide-react" not in icons
    assert "https://" not in icons
    assert "cdn" not in icons.casefold()
    assert 'stroke-width", "2"' in icons
    for icon_name in (
        "search", "download", "upload", "save", "pencil", "trash-2",
        "log-in", "log-out", "calendar", "copy", "arrow-left",
        "arrow-right", "shield-check",
    ):
        assert icon_name in icons


def test_common_button_variants_and_accessible_icon_rules_are_shared():
    css = (ROOT / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")
    icons = (ROOT / "static" / "js" / "ui-icons.js").read_text(encoding="utf-8")

    for selector in (
        ".btn-primary", ".btn-secondary", ".btn-outline", ".btn-ghost",
        ".btn-danger", ".btn-small", ".btn-lg", ".btn-icon", ".ui-icon",
    ):
        assert selector in css
    assert "focus-visible" in css
    assert '[aria-disabled="true"]' in css
    assert 'svg.setAttribute("aria-hidden", "true")' in icons
    assert 'svg.setAttribute("focusable", "false")' in icons


def test_search_asset_uses_lucide_stroke_geometry():
    search = (ROOT / "static" / "img" / "search.svg").read_text(encoding="utf-8")
    assert 'viewBox="0 0 24 24"' in search
    assert 'fill="none"' in search
    assert 'stroke="currentColor"' in search
    assert '<circle cx="11" cy="11" r="8"' in search

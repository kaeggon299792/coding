from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_shared_vega_layer_is_loaded_sitewide_without_a_new_font_stack():
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "site-components.css").read_text(encoding="utf-8")

    assert "css/site-components.css" in base
    assert "js/vega-select.js" in base
    assert "@font-face" not in css
    assert "font-family" not in css
    assert "DM Sans" not in css
    assert "fonts/" not in css
    assert "font: inherit" in css


def test_shared_tokens_cover_the_vega_component_language():
    css = (ROOT / "static" / "css" / "site-components.css").read_text(encoding="utf-8")

    for token in (
        "--ui-background",
        "--ui-foreground",
        "--ui-card",
        "--ui-popover",
        "--ui-muted",
        "--ui-muted-foreground",
        "--ui-border",
        "--ui-primary",
        "--ui-danger",
        "--ui-ring",
        "--ui-radius",
        "--ui-control-height",
        "--ui-shadow-xs",
        "--ui-shadow-popover",
    ):
        assert token in css


def test_shared_components_cover_controls_surfaces_and_navigation():
    css = (ROOT / "static" / "css" / "site-components.css").read_text(encoding="utf-8")

    for selector in (
        ".btn-primary",
        ".btn-secondary",
        ".btn-outline",
        ".btn-ghost",
        ".btn-icon",
        ".login-button",
        ".vega-select-trigger",
        ".vega-select-content",
        ".vega-select-option",
        'input[type="checkbox"]',
        'input[type="radio"]',
        ".badge",
        ".news-pagination",
        ".company-expert-tabs",
        "table.data-table",
        ".topbar-nav",
        ".global-language-switch",
        '[role="tooltip"]',
    ):
        assert selector in css

    assert "@media (max-width: 760px)" in css
    assert "prefers-reduced-motion: reduce" in css


def test_custom_select_preserves_native_elements_and_advanced_native_opt_outs():
    script = (ROOT / "static" / "js" / "vega-select.js").read_text(encoding="utf-8")

    assert 'document.querySelectorAll("select").forEach(wrapNativeSelect)' in script
    assert "native.before(root)" in script
    assert "root.append(native)" in script
    assert "native.multiple" in script
    assert 'native.getAttribute("size")' in script
    assert 'data-native-select' in script
    assert 'new Event("input", {bubbles: true})' in script
    assert 'new Event("change", {bubbles: true})' in script
    assert 'native.form?.addEventListener("reset"' in script


def test_company_vega_layer_uses_the_existing_site_font_variable():
    css = (ROOT / "static" / "css" / "vega-components.css").read_text(encoding="utf-8")
    template = (ROOT / "templates" / "companies.html").read_text(encoding="utf-8")

    assert "--ui-font-sans: var(--font-body)" in css
    assert "DMSans-Variable-Latin.woff2" in template

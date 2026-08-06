from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_company_period_select_keeps_native_form_contract_as_fallback():
    template = (ROOT / "templates" / "companies.html").read_text(encoding="utf-8")
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")

    assert 'name="days"' in template
    assert 'onchange="this.form.submit()"' in template
    assert "data-vega-select-native" in template
    for value in (30, 90, 180, 365):
        assert f'value="{value}"' in template
        assert f"days == {value}" in template
    assert "css/vega-components.css" in template
    assert "js/vega-select.js" in base


def test_vega_select_is_accessible_and_avoids_native_mobile_popup_after_enhancement():
    script = (ROOT / "static" / "js" / "vega-select.js").read_text(encoding="utf-8")

    assert 'setAttribute("role", "listbox")' in script
    assert 'setAttribute("role", "option")' in script
    assert 'setAttribute("aria-expanded", "false")' in script
    assert 'setAttribute("aria-selected"' in script
    assert 'setAttribute("aria-activedescendant"' in script
    assert 'native.setAttribute("aria-hidden", "true")' in script
    assert "native.tabIndex = -1" in script
    assert "label.htmlFor = triggerId" in script
    assert 'event.key === "Escape"' in script
    assert 'event.key === "ArrowDown"' in script
    assert 'event.key === "Enter"' in script
    assert 'event.key === " "' in script
    assert 'document.addEventListener("pointerdown", closeFromOutside)' in script


def test_vega_select_preserves_change_events_and_viewport_positioning():
    script = (ROOT / "static" / "js" / "vega-select.js").read_text(encoding="utf-8")

    assert 'new Event("input", {bubbles: true})' in script
    assert 'new Event("change", {bubbles: true})' in script
    assert "window.innerHeight" in script
    assert 'listbox.dataset.side = side' in script
    assert 'position: fixed' in (ROOT / "static" / "css" / "vega-components.css").read_text(
        encoding="utf-8"
    )


def test_vega_tokens_use_the_existing_site_font_system():
    css = (ROOT / "static" / "css" / "vega-components.css").read_text(encoding="utf-8")
    template = (ROOT / "templates" / "companies.html").read_text(encoding="utf-8")

    for token in (
        "--ui-font-sans",
        "--ui-background",
        "--ui-foreground",
        "--ui-muted",
        "--ui-border",
        "--ui-primary",
        "--ui-radius",
        "--ui-shadow-popover",
    ):
        assert token in css
    assert ".company-360-page" in css
    assert ".vega-select-trigger" in css
    assert ".vega-select-content" in css
    assert ".vega-select-option" in css
    assert "prefers-reduced-motion: reduce" in css
    assert "--ui-font-sans: var(--font-body)" in css
    assert "@font-face" in css
    assert "DMSans-Variable-Latin.woff2" in template
    assert (ROOT / "static" / "fonts" / "DMSans-Variable-Latin.woff2").stat().st_size > 10_000
    assert (ROOT / "static" / "fonts" / "DMSans-OFL.txt").exists()


def test_sitewide_component_layer_preserves_existing_font_system():
    css = (ROOT / "static" / "css" / "site-components.css").read_text(encoding="utf-8")
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    dashboard_css = (ROOT / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")

    assert "css/site-components.css" in base
    assert "font-family" not in css
    assert "@font-face" not in css
    assert "--font-body:" in dashboard_css
    assert "--font-display:" in dashboard_css
    assert "body {" in dashboard_css
    assert "font-family: var(--font-body)" in dashboard_css


def test_sitewide_select_enhancement_keeps_native_contract_and_opt_outs():
    script = (ROOT / "static" / "js" / "vega-select.js").read_text(encoding="utf-8")

    assert 'document.querySelectorAll("select").forEach(wrapNativeSelect)' in script
    assert 'native.multiple' in script
    assert 'native.getAttribute("size")' in script
    assert 'native.hasAttribute("data-native-select")' in script
    assert 'native.dataset.vegaSelectNative = ""' in script
    assert 'native.addEventListener("invalid"' in script

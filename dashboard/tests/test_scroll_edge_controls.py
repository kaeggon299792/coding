from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_scroll_edge_controls_include_conditional_top_and_bottom_actions():
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")

    assert 'id="back-to-top"' in base
    assert 'data-ui-icon="arrow-up"' in base
    assert 'id="back-to-bottom"' in base
    assert 'data-ui-icon="arrow-down"' in base
    assert "setVisible(topButton, window.scrollY > 480)" in base
    assert "setVisible(bottomButton, remaining > 48)" in base
    assert "window.scrollTo({top: documentHeight" in base
    assert ".back-to-top { right: 18px; }" in css
    assert ".back-to-bottom { right: 62px; }" in css

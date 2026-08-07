from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_archive_template_uses_board_specific_list_copy():
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    template = (ROOT / "templates" / "diary_board.html").read_text(encoding="utf-8")

    assert '"list_title": "리뷰 모음"' in app_source
    assert '"empty_description": "첫 리뷰를 작성해보세요."' in app_source
    assert "{{ archive_settings.list_title }}" in template
    assert "{{ archive_settings.empty_description }}" in template


def test_navigation_shadows_and_alignment_animation_are_removed():
    site_css = (ROOT / "static" / "css" / "site-components.css").read_text(encoding="utf-8")
    dashboard_css = (ROOT / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")

    assert ".global-language-switch nav { box-shadow: none; }" in site_css
    assert ".global-language-switch { backdrop-filter: none; }" in site_css
    assert ".topbar-private-menu > div { box-shadow: none; }" in site_css
    assert "transition:margin-left" not in dashboard_css


def test_page_width_regressions_are_bounded_and_centered():
    css = (ROOT / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")

    assert ".fund-scenario-page{box-sizing:border-box;width:min(1440px,calc(100% - 48px));max-width:1440px" in css
    assert ".bug-report-page{box-sizing:border-box;width:min(1180px,calc(100% - 48px));" in css
    assert ".fund-scenario-page,.bug-report-page{width:calc(100% - 32px)" in css

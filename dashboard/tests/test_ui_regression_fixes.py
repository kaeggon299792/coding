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
    assert ".topbar-nav > a.active { border-bottom-color: transparent; }" in site_css
    assert ".topbar-nav .global-language-switch a.active { margin: 0; border: 0; }" in site_css
    assert "transition:margin-left" not in dashboard_css


def test_page_width_regressions_are_bounded_and_centered():
    css = (ROOT / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")

    assert ".fund-scenario-page{box-sizing:border-box;width:min(1440px,calc(100% - 48px));max-width:1440px" in css
    assert ".bug-report-page{box-sizing:border-box;width:min(1180px,calc(100% - 48px));" in css
    assert ".fund-scenario-page,.bug-report-page{width:calc(100% - 32px)" in css


def test_account_picture_uses_the_existing_button_system_around_native_upload():
    template = (ROOT / "templates" / "account.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "site-components.css").read_text(encoding="utf-8")

    assert 'type="file" name="picture"' in template
    assert 'class="btn btn-outline account-picture-button"' in template
    assert 'data-account-picture-name' in template
    assert '.account-picture-picker > input[type="file"]' in css


def test_source_data_controls_are_collapsed_until_a_query_is_active():
    template = (ROOT / "templates" / "source_download.html").read_text(encoding="utf-8")

    assert '<details class="source-download-disclosure"{% if request.args %} open{% endif %}>' in template
    assert "원천 데이터 조회·다운로드" in template
    assert "원천 데이터 다운로드" in template


def test_admin_navigation_is_iconized_and_bounded():
    topbar = (ROOT / "templates" / "_topbar.html").read_text(encoding="utf-8")
    sidebar = (ROOT / "templates" / "_admin_sidebar.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "site-components.css").read_text(encoding="utf-8")

    assert 'data-ui-icon="layout-dashboard">관리자 전용' in topbar
    assert 'class="admin-global-sidebar"' in sidebar
    assert 'data-ui-icon="briefcase"' in sidebar
    assert ".admin-global-sidebar" in css
    assert "max-width: 1160px" in css

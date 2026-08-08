from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_primary_navigation_matches_confirmed_ia():
    markup = (ROOT / "templates" / "_topbar.html").read_text(encoding="utf-8")
    for label in (
        "홈", "뉴스", "시장 정보", "기업정보", "법률·규제", "자료실", "게시판",
        "통합검색", "회원전용", "회원정보관리", "관리자 전용",
    ):
        assert label in markup
    assert "파라디안 전용" not in markup
    assert ">데이터<" not in markup
    assert ">공시·재무<" not in markup
    assert ">기업 360°<" not in markup

    topbar_nav = markup.split('<nav class="topbar-nav"', 1)[1].split("</nav>", 1)[0]
    assert topbar_nav.index(">뉴스</a>") < topbar_nav.index(">채용</a>")
    assert topbar_nav.index(">채용</a>") < topbar_nav.index(">시장 정보</a>")
    assert "url_for('salary_trend_page')" in topbar_nav
    assert ">블로그</a>" not in topbar_nav
    board_subnav = (ROOT / "templates" / "_board_subnav.html").read_text(encoding="utf-8")
    for label in ("자유 게시판", "공지사항", "리뷰", "버그 및 건의"):
        assert f">{label}</a>" in board_subnav
    member_subnav = (ROOT / "templates" / "_member_subnav.html").read_text(encoding="utf-8")
    for label in ("업무노트", "아카이브", "데이터 다운"):
        assert f">{label}</a>" in member_subnav
    assert "member_area.telegram" in member_subnav
    assert "t('텔레그램 알림')" in member_subnav
    assert ">메일</a>" not in member_subnav
    dashboard_css = (ROOT / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")
    assert ".member-subnav.data-subnav[data-align-subnav]{justify-content:flex-start" in dashboard_css
    assert "@media(max-width:760px){.member-subnav.data-subnav[data-align-subnav]{justify-content:flex-start" in dashboard_css
    assert ".member-subnav.data-subnav[data-align-subnav]::-webkit-scrollbar{display:none}" in dashboard_css
    base_template = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert 'if (nav.hidden || !nav.classList.contains("is-compact")) return;' in base_template
    assert 'const desktop = window.matchMedia("(min-width: 761px)").matches;' not in base_template
    assert 'window.matchMedia("(max-width: 760px)").matches' in base_template
    assert "topbarStrip.scrollLeft = Math.max" in base_template
    assert "languageSwitch?.open && !languageSwitch.contains(event.target)" in base_template
    assert 'languageSwitch.removeAttribute("open")' in base_template
    assert not (ROOT / "templates" / "_blog_subnav.html").exists()
    assert ">관리자 전용</a>" not in topbar_nav


def test_recruitment_submenu_starts_with_salary_ratings():
    markup = (ROOT / "templates" / "_data_subnav.html").read_text(encoding="utf-8")
    recruitment = markup.split("request.endpoint in recruitment_endpoints", 1)[1]
    recruitment = recruitment.split("{% elif request.endpoint in company_endpoints %}", 1)[0]
    labels = ["연봉·평점", "복리후생", "채용정보", "족보"]
    positions = [recruitment.index(f">{label}</a>") for label in labels]
    assert positions == sorted(positions)


def test_profile_popover_has_large_avatar_and_personal_greeting():
    markup = (ROOT / "templates" / "_topbar.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")
    assert 'class="topbar-profile-hero"' in markup
    assert 'class="topbar-profile-photo"' in markup
    assert "안녕하세요, {{ current_user.name or current_user.username }}님" in markup
    assert "topbar-profile-large-avatar" in markup
    assert ".topbar-profile-photo{" in css
    assert "width:76px;height:76px" in css
    assert "member-avatar-third-ring" not in markup
    for orbit_point in ("16%", "49.3%", "82.7%"):
        assert orbit_point in css
    assert "animation:member-avatar-orbit 17s linear infinite" in css
    assert "animation:member-avatar-flat-breathe 11s ease-in-out infinite" in css
    assert "animation:member-avatar-photo-breathe 11s ease-in-out infinite" in css
    assert "border-width:2px" in css
    assert css.count("color-mix(in srgb,var(--grade-glow) 68%,#202936)") == 3
    assert ".topbar-profile-menu{z-index:1400}" in css
    assert "body.cinematic-home .global-language-switch.is-embedded{z-index:1500}" in css


def test_profile_and_language_menus_are_mutually_exclusive():
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert 'const profileMenu = document.querySelector(".topbar-profile-menu")' in base
    assert 'document.addEventListener("pointerdown"' in base
    assert "!profileMenu.contains(event.target)" in base
    assert 'event.key === "Escape"' in base
    assert 'if (profileMenu.open) languageSwitch.removeAttribute("open")' in base
    assert 'if (languageSwitch.open) profileMenu.removeAttribute("open")' in base
    assert 'topbarActions.insertBefore(languageSwitch, profileMenu' in base
    assert 'window.matchMedia("(max-width: 768px)").matches' in base
    assert ".topbar-actions>.global-language-switch" in (
        ROOT / "static" / "css" / "dashboard.css"
    ).read_text(encoding="utf-8")
    topbar = (ROOT / "templates" / "_topbar.html").read_text(encoding="utf-8")
    assert "{% if current_user_role == 'admin' %}<a" in topbar
    assert ">관리자 전용</a>{% endif %}" in topbar


def test_mobile_navigation_and_company_filters_are_present():
    topbar = (ROOT / "templates" / "_topbar.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")
    company_news = (ROOT / "templates" / "company_news.html").read_text(encoding="utf-8")
    assert 'class="topbar-nav"' in topbar
    assert ".topbar-nav { display: flex" in css
    assert "overflow-x: auto" in css
    assert "white-space: nowrap" in css
    assert (
        "body.cinematic-home .topbar,body.cinematic-home .public-header"
        "{position:relative;z-index:60}" in css
    )
    assert 'class="company-news-filter"' in company_news
    for field in ("q", "company", "category", "importance", "analysis", "impact", "days"):
        assert f'name="{field}"' in company_news
    from services.company_intelligence import COMPANY_NEWS_CATEGORY_LABELS

    for category in ("경영·인사", "투자·시설", "재무·실적", "채용", "기타"):
        assert category in COMPANY_NEWS_CATEGORY_LABELS.values()


def test_english_catalog_and_sitemap_match_ia():
    import json

    catalog = json.loads(
        (ROOT / "translations" / "catalog.json").read_text(encoding="utf-8")
    )["text"]
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert catalog["시장 정보"] == "Market Intelligence"
    assert catalog["기업정보"] == "Company Intelligence"
    assert catalog["법률·규제"] == "Legal & Regulatory"
    assert catalog["자료실"] == "Resource Library"
    assert catalog["게시판"] == "Boards"
    for label in ("시장 정보", "기업정보", "법률·규제", "자료실", "게시판"):
        assert f'"label": "{label}"' in app_source
    assert '"label": "블로그"' not in app_source


def test_canonical_routes_and_legacy_redirect_map_match_navigation():
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    for route in (
        '/news', '/news/overseas', '/market/casino-industry', '/market/stocks',
        '/companies/disclosures', '/companies/reports', '/companies/salary-ratings',
        '/companies/comparison', '/companies/expert',
        '/companies/recruitment', '/resources/source-data', '/board/bug-reports',
        '/laws', '/companies', '/search', '/sitemap',
    ):
        assert route in app_source
    for legacy_route in (
        '/performance/news', '/performance/overseas-news', '/disclosures',
        '/library', '/tips', '/bug-reports',
    ):
        assert legacy_route in app_source


def test_changed_templates_compile_in_flask():
    import app as app_module

    for template in (
        "_topbar.html", "_data_subnav.html", "public_home.html", "companies.html",
        "company_comparison.html", "company_expert.html",
        "disclosures.html", "company_news.html", "action_items.html",
        "action_item_detail.html", "laws.html", "account.html", "sitemap.html",
    ):
        app_module.app.jinja_env.get_template(template)


def test_page_loader_has_no_forced_completion_delay():
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "setTimeout(finish, 240)" not in base
    assert 'loader.classList.add("is-hidden")' in base


def test_desktop_topbar_hover_reuses_submenu_container_without_changing_mobile():
    topbar = (ROOT / "templates" / "_topbar.html").read_text("utf-8")
    base = (ROOT / "templates" / "base.html").read_text("utf-8")
    css = (ROOT / "static" / "css" / "dashboard.css").read_text("utf-8")
    assert "data-topbar-menu" in topbar
    assert "data-topbar-submenu" in topbar
    assert "topbar-submenu-preview-active" in base
    assert '(min-width: 761px) and (hover: hover)' in base
    assert "@media(max-width:760px){.topbar-hover-subnav{display:none!important}}" in css


def test_legacy_footer_does_not_duplicate_the_shared_legal_footer():
    footer = (ROOT / "templates" / "_footer.html").read_text(encoding="utf-8")
    legal_footer = (ROOT / "templates" / "_legal_footer.html").read_text(encoding="utf-8")
    dashboard_css = (ROOT / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")
    assert "Business, Executed" not in footer
    assert "© 2026 CASINO IN" in legal_footer
    assert ".legal-footer{" in dashboard_css
    assert "letter-spacing:.01em;text-align:center" in dashboard_css


def test_market_sparklines_do_not_render_distorted_endpoint_circles():
    markup = (ROOT / "templates" / "market_trend.html").read_text(encoding="utf-8")
    assert "<circle" not in markup
    assert "final_point" not in markup

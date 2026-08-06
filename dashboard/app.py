"""
경영기획 인텔리전스 대시보드 - Flask 엔트리포인트.

기존 portfolio/app.py의 세션 쿠키 보안 설정 패턴을 재사용한다.
뉴스 DB는 읽기 전용으로만 연결하고 대시보드 자체 데이터만 dashboard.db에 쓴다.
"""

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlsplit
from xml.etree.ElementTree import Element, SubElement, register_namespace, tostring

import bleach
import markdown
from flask import (
    Flask, abort, flash, g, jsonify, redirect, render_template, request, send_file,
    session, url_for,
)
from markupsafe import Markup
from werkzeug.middleware.proxy_fix import ProxyFix

import config
from auth import (
    admin_required,
    auth_bp,
    current_menu_permissions,
    get_csrf_token,
    init_oauth,
    login_required,
    refresh_current_session,
    restore_remembered_login,
    validate_csrf,
)
from dashboard_db import queries
from extensions import dashboard_db
from services import (
    ai_insights,
    casino_industry,
    casino_insights,
    casino_market_share,
    casino_statistics,
    company_comparison,
    company_expert,
    company_intelligence,
    content_translation,
    document_library,
    economic_data,
    editor_images,
    fund_increase_scenario,
    market_data,
    localization_management,
    membership,
    news_reader,
    overseas_news,
    official_document_manager,
    performance_parser,
    portfolio_admin,
    portfolio_content,
    rss_feed,
    salary_data,
    security_audit,
    security_monitor,
    site_preferences,
    source_data_repository,
    telegram_alert,
    unified_search,
)
from official_docs import official_docs_bp
from seo_content import LOCALIZED_SEO_PAGE_COPY
from tips import tips_bp
from localization import (
    LocalePrefixMiddleware,
    SUPPORTED_LOCALES,
    alternate_paths,
    extract_translatable_html_strings,
    load_catalog,
    locale_from_environ,
    meta_for,
    translate_html,
    translate_structure,
    translate_source_label,
    translate_text,
)
from utils import display_y_drive_path, escape_html, now_kst, setup_logger, today_kst_str

logger = setup_logger("dashboard_app")
_last_account_retention_cleanup = 0.0
_last_activity_log_retention_cleanup = 0.0
_localization_render_scan_at = {}

ANONYMOUS_ACTIVITY_DEDUPE_MINUTES = 5
AUTHENTICATED_ACTIVITY_DEDUPE_MINUTES = 1
ANONYMOUS_ACTIVITY_PER_IP_DAILY_LIMIT = 200
ANONYMOUS_ACTIVITY_GLOBAL_DAILY_LIMIT = 5000

CANONICAL_URL = config.DASHBOARD_PUBLIC_URL.rstrip("/")
_CANONICAL_PARTS = urlsplit(CANONICAL_URL)
CANONICAL_SCHEME = (_CANONICAL_PARTS.scheme or "https").lower()
CANONICAL_HOST = (_CANONICAL_PARTS.netloc or "").split(":", 1)[0].lower()
SEO_IMAGE_URL = f"{CANONICAL_URL}/static/img/casino-in-logo.png"
LEGACY_PUBLIC_PATH_PREFIXES = tuple(sorted({
    "/dashboard": "/",
    "/paradian": "/admin",
    "/performance/source-download": "/resources/source-data",
    "/performance/casino-industry": "/market/casino-industry",
    "/performance/overseas-news": "/news/overseas",
    "/performance/recruitment": "/companies/recruitment",
    "/performance/salaries": "/companies/salary-ratings",
    "/performance/holidays": "/market/holidays",
    "/performance/economy": "/market/exchange-rates-and-oil",
    "/performance/tourism": "/market/tourism",
    "/performance/markets": "/market/stocks",
    "/performance/news": "/news",
    "/performance": "/admin/performance",
    "/disclosures": "/companies/disclosures",
    "/library": "/companies/reports",
    "/tips": "/resources",
    "/action-items": "/board/bug-reports",
    "/bug-reports": "/board/bug-reports",
}.items(), key=lambda item: len(item[0]), reverse=True))
INDEXABLE_ENDPOINTS = {
    "public_home",
    "market_trend_page",
    "related_news_page",
    "overseas_news_page",
    "tourism_trend_page",
    "economic_trend_page",
    "holiday_calendar_page",
    "salary_trend_page",
    "recruitment_page",
    "company_recruitment_guide_page",
    "casino_industry_page",
    "casino_insights_page",
    "casino_market_share_page",
    "casino_visitors_page",
    "casino_revenue_page",
    "casino_fund_page",
    "disclosures_page",
    "laws_page",
    "legislation_page",
    "fund_increase_scenario_page",
    "companies_page",
    "company_comparison_page",
    "company_expert_page",
    "company_benefits_page",
    "company_news_page",
    "research_library_page",
    "credits_page",
    "tips.list_page",
    "tips.sites_page",
    "tips.glossary_page",
    "tips.detail_page",
}
NOINDEX_ENDPOINTS = {
    "auth.login",
    "auth.register",
    "auth.user_management",
    "auth.membership_management",
    "auth.membership_user_detail",
    "auth.ai_settings",
    "auth.admin_logs",
    "auth.admin_tasks",
    "dashboard_home",
    "paradian_portal_page",
    "admin_portfolio_page",
    "performance_page",
    "source_download_page",
    "sitemap_page",
    "unified_search_page",
    "action_items_page",
    "action_item_detail",
    "community_board_page",
    "notice_board_page",
    "community_post_page",
    "diary_board_page",
    "diary_entry_page",
    "not_found_page",
}
LOCALIZATION_DISCOVERY_ENDPOINTS = INDEXABLE_ENDPOINTS | {
    "community_board_page",
    "notice_board_page",
    "community_post_page",
}
SITEMAP_STATIC_ENDPOINTS = (
    "public_home", "casino_industry_page", "casino_insights_page", "casino_market_share_page",
    "casino_visitors_page", "casino_revenue_page", "casino_fund_page",
    "related_news_page", "overseas_news_page", "market_trend_page",
    "tourism_trend_page", "economic_trend_page", "holiday_calendar_page",
    "salary_trend_page", "recruitment_page", "company_recruitment_guide_page",
    "disclosures_page", "laws_page", "legislation_page",
    "fund_increase_scenario_page", "companies_page",
    "company_comparison_page",
    "company_expert_page",
    "company_benefits_page", "company_news_page", "research_library_page",
    "tips.list_page", "tips.sites_page", "tips.glossary_page", "credits_page",
)
SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"
XHTML_NAMESPACE = "http://www.w3.org/1999/xhtml"
SITEMAP_PUBLIC_URL = "https://www.casinoin.kr"
register_namespace("", SITEMAP_NAMESPACE)
register_namespace("xhtml", XHTML_NAMESPACE)
SEO_PAGE_COPY = {
    "ko": {
        "public_home": (
            "Casino IN | 카지노 산업 정보와 인사이트",
            "국내외 카지노 기업, 관광객, 환율, 공시, 시장 동향과 산업 데이터를 한곳에서 확인하는 카지노 산업 인텔리전스 플랫폼입니다.",
        ),
        "casino_industry_page": (
            "국내 카지노 산업 | Casino IN",
            "국내 외국인전용 카지노 사업장 현황, 지역 분포, 매출과 이용객 데이터를 한 화면에서 확인합니다.",
        ),
        "casino_visitors_page": (
            "연도별 카지노 이용객 | Casino IN",
            "국내 카지노의 연도별 내국인·외국인 이용객 추이와 증감률을 확인합니다.",
        ),
        "casino_revenue_page": (
            "연도별 카지노 매출액 비율 | Casino IN",
            "국내 카지노의 연도별 매출과 시장 비중을 원화 환산 정보와 함께 비교합니다.",
        ),
        "casino_fund_page": (
            "카지노 기금 부과 현황 | Casino IN",
            "국내 카지노 사업자의 관광진흥개발기금 부과 현황을 연도별로 확인합니다.",
        ),
        "related_news_page": (
            "국내 카지노 산업 뉴스 | Casino IN",
            "국내 카지노·관광 산업 뉴스와 AI 관점 분석을 한곳에서 확인합니다.",
        ),
        "overseas_news_page": (
            "마카오·일본 카지노 해외 뉴스 | Casino IN",
            "마카오와 일본 카지노·복합리조트 뉴스를 한글 번역과 원문 링크로 확인합니다.",
        ),
        "market_trend_page": (
            "카지노 기업 주가 정보 | Casino IN",
            "국내 카지노 4사와 마카오 주요 카지노 운영사의 주가, 지수, 시가총액 흐름을 비교합니다.",
        ),
        "tourism_trend_page": (
            "외국인 관광객 통계 및 분석 | Casino IN",
            "국가별 방한 외래관광객 추이와 전년 대비 변화를 비교합니다.",
        ),
        "economic_trend_page": (
            "유가·환율 데이터 | Casino IN",
            "국내 유가와 주요 환율 흐름을 시계열 그래프로 확인합니다.",
        ),
        "holiday_calendar_page": (
            "국가별 연휴 캘린더 | Casino IN",
            "한국, 중국, 일본, 대만, 몽골 등 주요 국가의 연휴 일정을 비교합니다.",
        ),
        "salary_trend_page": (
            "카지노 업계 연봉 정보 | Casino IN",
            "카지노 4사와 비교 업계 평균연봉의 최근 공개값과 월별 변화를 확인합니다.",
        ),
        "recruitment_page": (
            "카지노 업계 채용 정보 | Casino IN",
            "잡코리아, 사람인, 인크루트 기반 카지노 관련 채용공고를 구조화해 보여줍니다.",
        ),
        "company_recruitment_guide_page": (
            "카지노 기업 채용 족보 | Casino IN",
            "기업별 면접·실기 질문과 전형 분위기 기록을 확인합니다.",
        ),
        "disclosures_page": (
            "카지노 기업 공시정보 | Casino IN",
            "관심 카지노 기업의 DART 공시, 제출인, AI 요약을 한곳에서 확인합니다.",
        ),
        "laws_page": (
            "카지노 법률·규제 모니터링 | Casino IN",
            "카지노 영업준칙과 관광진흥법 등 현행 법령과 최근 변경 이력을 확인합니다.",
        ),
        "legislation_page": (
            "카지노 입법동향 | Casino IN",
            "카지노 관련 정부입법예고와 국회 발의·심사 의안을 분리해 확인합니다.",
        ),
        "fund_increase_scenario_page": (
            "관광진흥개발기금 인상 시나리오 | Casino IN",
            "2025년 카지노 운영사 재무자료를 기준으로 관광진흥개발기금 10%에서 15% 인상 시 영업이익 영향을 비교합니다.",
        ),
        "companies_page": (
            "국내외 카지노 기업 분석 | Casino IN",
            "파라다이스, GKL, 강원랜드, 롯데관광개발 등 주요 기업 정보를 비교 분석합니다.",
        ),
        "company_news_page": (
            "카지노 기업별 뉴스 | Casino IN",
            "주요 국내 카지노 기업 뉴스를 AI 분류 기준으로 비교합니다.",
        ),
        "research_library_page": (
            "카지노 시장 분석과 인사이트 | Casino IN",
            "증권사·산업 리포트와 AI 분석을 바탕으로 카지노 산업 인사이트를 제공합니다.",
        ),
        "tips.list_page": (
            "자료실 | Casino IN",
            "업무 자동화, 보고서, 데이터 분석 노하우를 정리한 공개 자료실입니다.",
        ),
        "tips.sites_page": (
            "관련 사이트 모음 | Casino IN",
            "카지노 산업 조사와 업무에 유용한 관련 사이트 링크를 모아 제공합니다.",
        ),
        "credits_page": (
            "사이트 안내 | Casino IN",
            "Casino IN의 대표 데이터 제공기관, 이용 안내와 회원등급을 안내합니다.",
        ),
        "unified_search_page": (
            "통합검색 | Casino IN",
            "뉴스, 공시, 법령, 리포트 등 공개 카지노 산업 자료를 통합 검색합니다.",
        ),
        "action_items_page": (
            "버그 및 건의 | Casino IN",
            "Casino IN의 오류를 제보하거나 기능 개선 의견을 남길 수 있습니다.",
        ),
        "community_board_page": (
            "자유 게시판 | Casino IN",
            "카지노 산업과 업무 정보를 자유롭게 나누는 공개 게시판입니다.",
        ),
        "notice_board_page": (
            "공지사항 | Casino IN",
            "Casino IN의 주요 안내와 운영 공지를 확인합니다.",
        ),
        "auth.login": (
            "로그인 | Casino IN",
            "Casino IN 계정으로 안전하게 로그인합니다.",
        ),
        "auth.register": (
            "가입 신청 | Casino IN",
            "Casino IN 계정 사용을 위한 가입 승인을 신청합니다.",
        ),
        "sitemap_page": (
            "사이트맵 | Casino IN",
            "Casino IN의 공개 메뉴와 페이지 구조를 확인할 수 있는 사이트맵입니다.",
        ),
    },
    "en": {
        "public_home": (
            "Casino IN | Casino Industry Information and Insights",
            "An intelligence platform for casino companies, tourism flows, FX, disclosures, market trends, and industry data.",
        ),
        "casino_industry_page": (
            "Korea Casino Industry | Casino IN",
            "Explore Korean foreigner-only casino properties, locations, revenue, and visitor data in one place.",
        ),
        "casino_visitors_page": (
            "Annual Casino Visitors | Casino IN",
            "Review annual visitor volumes and year-over-year changes across Korea's casino market.",
        ),
        "casino_revenue_page": (
            "Annual Casino Revenue Share | Casino IN",
            "Compare annual casino revenue and market share with Korean won reference values.",
        ),
        "casino_fund_page": (
            "Casino Tourism Fund Assessments | Casino IN",
            "Review annual Tourism Promotion and Development Fund assessments for Korean casino operators.",
        ),
        "related_news_page": (
            "Korean Casino Industry News | Casino IN",
            "Follow Korean casino and travel-industry news with AI commentary and issue tracking.",
        ),
        "overseas_news_page": (
            "Macau and Japan Casino News | Casino IN",
            "Follow Macau and Japan casino and integrated-resort news with original sources and Korean translations.",
        ),
        "market_trend_page": (
            "Casino Stock Market Data | Casino IN",
            "Compare listed Korean casino operators and major Macau gaming stocks with recent price trends and market caps.",
        ),
        "tourism_trend_page": (
            "Inbound Tourism Trends | Casino IN",
            "Compare inbound visitor trends by country and year-over-year change.",
        ),
        "economic_trend_page": (
            "Fuel and FX Trends | Casino IN",
            "Track Korean retail fuel prices and major exchange-rate movements in one dashboard.",
        ),
        "holiday_calendar_page": (
            "Regional Holiday Calendar | Casino IN",
            "Review holiday schedules across Korea, China, Japan, Taiwan, Mongolia, and shared observances.",
        ),
        "salary_trend_page": (
            "Casino Compensation Data | Casino IN",
            "Review public average salary disclosures for Korean casino operators and benchmark industries.",
        ),
        "recruitment_page": (
            "Casino Recruitment Signals | Casino IN",
            "Browse structured casino-related job postings collected from major Korean hiring platforms.",
        ),
        "company_recruitment_guide_page": (
            "Casino Company Interview Guide | Casino IN",
            "Review company-specific interview and practical-test questions and atmosphere notes.",
        ),
        "disclosures_page": (
            "Casino Company Disclosures | Casino IN",
            "Monitor DART filings, submitters, and AI summaries for tracked casino companies.",
        ),
        "laws_page": (
            "Casino Laws and Regulations | Casino IN",
            "Review current casino operating standards, monitored laws, and recent legal changes.",
        ),
        "legislation_page": (
            "Casino Legislative Developments | Casino IN",
            "Track government legislative notices and casino-related National Assembly bills.",
        ),
        "fund_increase_scenario_page": (
            "Tourism Fund Increase Scenarios | Casino IN",
            "Compare the operating-profit impact of a hypothetical Tourism Promotion and Development Fund increase from 10% to 15% using 2025 financial data.",
        ),
        "companies_page": (
            "Casino Company Analysis | Casino IN",
            "Compare Paradise, GKL, Kangwon Land, Lotte Tour Development, and other casino-linked companies.",
        ),
        "company_news_page": (
            "Casino Company News | Casino IN",
            "Compare news about major Korean casino operators using AI issue categories.",
        ),
        "research_library_page": (
            "Casino Market Research and Insights | Casino IN",
            "Review broker reports, industry research, and AI analysis for the casino sector.",
        ),
        "tips.list_page": (
            "Knowledge Library | Casino IN",
            "Access public guides on automation, reporting, analytics, and operational know-how.",
        ),
        "tips.sites_page": (
            "Reference Sites | Casino IN",
            "A curated collection of external reference sites for casino-industry research and operations.",
        ),
        "credits_page": (
            "Site Guide | Casino IN",
            "Learn about Casino IN's information policy, representative data providers, and membership grades.",
        ),
        "unified_search_page": (
            "Unified Search | Casino IN",
            "Search public casino-industry news, filings, laws, and research in one place.",
        ),
        "action_items_page": (
            "Bug Reports and Suggestions | Casino IN",
            "Report site issues or submit feature suggestions for Casino IN.",
        ),
        "community_board_page": (
            "Community Board | Casino IN",
            "Read and discuss casino-industry and workplace topics on the public board.",
        ),
        "auth.login": (
            "Sign In | Casino IN",
            "Sign in securely to your Casino IN account.",
        ),
        "auth.register": (
            "Request an Account | Casino IN",
            "Request approval for a Casino IN account.",
        ),
        "sitemap_page": (
            "Sitemap | Casino IN",
            "Browse the public page structure of Casino IN.",
        ),
    },
}
for _seo_locale, _seo_pages in LOCALIZED_SEO_PAGE_COPY.items():
    SEO_PAGE_COPY.setdefault(_seo_locale, {}).update(_seo_pages)
_STRIP_TAGS_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")

app = Flask(__name__)
if not config.FLASK_SECRET_KEY:
    raise RuntimeError("FLASK_SECRET_KEY must be configured before the application starts")
app.secret_key = config.FLASK_SECRET_KEY
app.permanent_session_lifetime = timedelta(hours=config.SESSION_ABSOLUTE_HOURS)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=config.SESSION_COOKIE_SECURE,
    PREFERRED_URL_SCHEME="https",
    MAX_CONTENT_LENGTH=max(
        config.RESEARCH_MAX_FILE_BYTES,
        config.OFFICIAL_DOC_MAX_UPLOAD_MB * 1024 * 1024,
        config.TIPS_MAX_ATTACHMENT_BYTES,
    ) + (512 * 1024),
)
app.wsgi_app = LocalePrefixMiddleware(
    ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
)

init_oauth(app)
app.register_blueprint(auth_bp)
app.register_blueprint(official_docs_bp)
app.register_blueprint(tips_bp)

ENDPOINT_PERMISSIONS = {
    "action_items_page": "bug_reports",
    "create_action_item_route": "bug_reports",
    "action_item_detail": "bug_reports",
    "add_action_item_comment": "bug_reports",
    "edit_action_item_comment": "bug_reports",
    "delete_action_item_comment": "bug_reports",
    "update_action_item_route": "bug_reports",
    "delete_action_item_route": "bug_reports",
    "disclosures_page": "disclosures",
    "upload_ir_document": "disclosures",
    "download_ir_document": "disclosures",
    "reanalyze_ir_document": "disclosures",
    "delete_ir_document": "disclosures",
    "laws_page": "laws",
    "legislation_page": "laws",
    "fund_increase_scenario_page": "laws",
    "companies_page": "companies",
    "company_comparison_page": "companies",
    "company_expert_page": "companies",
    "company_benefits_page": "companies",
    "company_recruitment_guide_page": "companies",
    "company_news_page": "companies",
    "research_library_page": "research_library",
    "download_research_document": "research_library",
    "reanalyze_research_document": "research_library",
    "update_research_document_title": "research_library",
    "delete_research_document": "research_library",
    "unified_search_page": "unified_search",
}

PUBLIC_READ_ENDPOINTS = {
    "market_trend_page",
    "related_news_page",
    "overseas_news_page",
    "tourism_trend_page",
    "economic_trend_page",
    "holiday_calendar_page",
    "salary_trend_page",
    "recruitment_page",
    "casino_industry_page",
    "casino_insights_page",
    "casino_visitors_page",
    "casino_revenue_page",
    "casino_fund_page",
    "disclosures_page",
    "download_ir_document",
    "laws_page",
    "legislation_page",
    "fund_increase_scenario_page",
    "companies_page",
    "company_comparison_page",
    "company_expert_page",
    "company_benefits_page",
    "company_recruitment_guide_page",
    "company_news_page",
    "community_board_page",
    "notice_board_page",
    "community_post_page",
    "research_library_page",
    "download_research_document",
    "unified_search_page",
    "credits_page",
    "tips.list_page",
    "tips.sites_page",
    "tips.glossary_page",
    "tips.detail_page",
    "tips.attachment_file",
    "action_items_page",
}


def _request_scheme():
    forwarded = request.headers.get("X-Forwarded-Proto", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip().lower()
    return request.scheme.lower()


def _clean_text_snippet(value, limit=180):
    text = _SPACE_RE.sub(" ", _STRIP_TAGS_RE.sub(" ", value or "")).strip()
    if len(text) <= limit:
        return text
    shortened = text[:limit].rsplit(" ", 1)[0].strip()
    return f"{shortened}…"


def _date_only(value):
    if not value:
        return None
    candidate = str(value).strip()[:10]
    try:
        datetime.strptime(candidate, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None
    return candidate


def _alternate_absolute_urls(path):
    localized_paths = alternate_paths(path)
    return {
        locale: f"{SITEMAP_PUBLIC_URL}{localized_path}"
        for locale, localized_path in localized_paths.items()
    }


def _neutral_url_for(endpoint, **values):
    path = url_for(endpoint, **values)
    if path == "/en":
        return "/"
    if path.startswith("/en/"):
        return path[3:]
    return path


def _canonical_path(path):
    """Map a legacy public path to its one canonical IA-aligned path."""

    for legacy_prefix, canonical_prefix in LEGACY_PUBLIC_PATH_PREFIXES:
        if path == legacy_prefix:
            return canonical_prefix
        if path.startswith(f"{legacy_prefix}/"):
            path = f"{canonical_prefix}{path[len(legacy_prefix):]}"
            break
    if path not in {"/", "/official-docs/"} and path.endswith("/"):
        return path.rstrip("/")
    return path


def _localized_path(path):
    script_root = (request.script_root or "").rstrip("/")
    if path == "/":
        return f"{script_root}/" or "/"
    return f"{script_root}{path}"


def _canonical_request_url(path):
    target = f"{CANONICAL_URL}{_localized_path(path)}"
    if request.query_string:
        target = f"{target}?{request.query_string.decode('latin-1')}"
    return target


def _breadcrumb_schema(endpoint, locale, title, canonical_path):
    section_by_endpoint = {
        "related_news_page": ("뉴스", "/news"),
        "overseas_news_page": ("뉴스", "/news"),
        "casino_industry_page": ("시장 정보", "/market/casino-industry"),
        "casino_visitors_page": ("시장 정보", "/market/casino-industry"),
        "casino_revenue_page": ("시장 정보", "/market/casino-industry"),
        "casino_fund_page": ("시장 정보", "/market/casino-industry"),
        "market_trend_page": ("시장 정보", "/market/casino-industry"),
        "tourism_trend_page": ("시장 정보", "/market/casino-industry"),
        "economic_trend_page": ("시장 정보", "/market/casino-industry"),
        "holiday_calendar_page": ("시장 정보", "/market/casino-industry"),
        "companies_page": ("기업정보", "/companies"),
        "company_comparison_page": ("기업정보", "/companies"),
        "company_expert_page": ("기업정보", "/companies"),
        "company_benefits_page": ("기업정보", "/companies"),
        "company_recruitment_guide_page": ("기업정보", "/companies"),
        "company_news_page": ("기업정보", "/companies"),
        "disclosures_page": ("기업정보", "/companies"),
        "research_library_page": ("기업정보", "/companies"),
        "salary_trend_page": ("기업정보", "/companies"),
        "recruitment_page": ("기업정보", "/companies"),
        "laws_page": ("법률·규제", "/laws"),
        "legislation_page": ("법률·규제", "/laws"),
        "fund_increase_scenario_page": ("법률·규제", "/laws"),
        "tips.list_page": ("자료실", "/resources"),
        "tips.sites_page": ("자료실", "/resources"),
        "tips.glossary_page": ("자료실", "/resources"),
    }
    locale_prefix = "" if locale == "ko" else f"/{locale.lower()}"
    items = [{
        "@type": "ListItem",
        "position": 1,
        "name": translate_text("홈", locale),
        "item": f"{CANONICAL_URL}{locale_prefix}/",
    }]
    section = section_by_endpoint.get(endpoint)
    if section:
        section_label, section_path = section
        section_url = f"{CANONICAL_URL}{locale_prefix}{section_path}"
        if section_url != f"{CANONICAL_URL}{canonical_path}":
            items.append({
                "@type": "ListItem",
                "position": len(items) + 1,
                "name": translate_text(section_label, locale),
                "item": section_url,
            })
    if endpoint != "public_home":
        items.append({
            "@type": "ListItem",
            "position": len(items) + 1,
            "name": title.split(" | ", 1)[0],
            "item": f"{CANONICAL_URL}{canonical_path}",
        })
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": items,
    }


def _seo_defaults():
    locale = getattr(g, "locale", "ko")
    endpoint = request.endpoint or ""
    seo_paths = alternate_paths(request.path)
    canonical_path = seo_paths[locale]
    localized_copy = SEO_PAGE_COPY.get(locale, {})
    fallback_title, fallback_description = localized_copy.get(
        "public_home", SEO_PAGE_COPY["en"]["public_home"]
    )
    title, description = localized_copy.get(
        endpoint,
        (fallback_title, fallback_description),
    )
    robots = "index,follow" if endpoint in INDEXABLE_ENDPOINTS else "noindex,nofollow"
    language_tag = {
        "ko": "ko-KR",
        "en": "en-US",
        "ja": "ja-JP",
        "yue-HK": "yue-HK",
    }.get(locale, locale)
    page_schema = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": title,
        "url": f"{CANONICAL_URL}{canonical_path}",
        "description": description,
        "inLanguage": language_tag,
        "isPartOf": {
            "@type": "WebSite",
            "name": "Casino IN",
            "url": f"{CANONICAL_URL}/",
        },
    }
    structured_data = (
        [page_schema, _breadcrumb_schema(endpoint, locale, title, canonical_path)]
        if endpoint in INDEXABLE_ENDPOINTS else []
    )
    if endpoint == "public_home":
        website = {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": "Casino IN",
            "url": f"{CANONICAL_URL}/",
            "description": description,
            "inLanguage": language_tag,
            "potentialAction": {
                "@type": "SearchAction",
                "target": f"{CANONICAL_URL}/search?q={{search_term_string}}",
                "query-input": "required name=search_term_string",
            },
        }
        organization = {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": "Casino IN",
            "url": f"{CANONICAL_URL}/",
            "logo": SEO_IMAGE_URL,
        }
        structured_data = [
            website,
            organization,
            page_schema,
            _breadcrumb_schema(endpoint, locale, title, canonical_path),
        ]
    return {
        "seo_title": title,
        "seo_description": description,
        "seo_robots": robots,
        "seo_canonical_url": f"{CANONICAL_URL}{canonical_path}",
        "seo_hreflang_urls": {
            **{
                language: f"{CANONICAL_URL}{localized_path}"
                for language, localized_path in seo_paths.items()
            },
            "x-default": f"{CANONICAL_URL}{seo_paths['ko']}",
        },
        "seo_og_title": title,
        "seo_og_description": description,
        "seo_og_type": "website",
        "seo_og_url": f"{CANONICAL_URL}{canonical_path}",
        "seo_og_locale": {
            "ko": "ko_KR",
            "en": "en_US",
            "ja": "ja_JP",
            "yue-HK": "yue_HK",
        }.get(locale, "ko_KR"),
        "seo_og_locale_alternates": [
            value
            for key, value in {
                "ko": "ko_KR",
                "en": "en_US",
                "ja": "ja_JP",
                "yue-HK": "yue_HK",
            }.items()
            if key != locale
        ],
        "seo_image_url": SEO_IMAGE_URL,
        "seo_image_alt": "Casino IN logo",
        "seo_twitter_card": "summary_large_image",
        "seo_json_ld": structured_data,
    }


@app.before_request
def establish_request_security():
    g.locale = locale_from_environ(request.environ)
    # Redirect and error responses also pass through the CSP hook, so create
    # the nonce before any early return.
    g.csp_nonce = secrets.token_urlsafe(18)
    host = request.host.split(":", 1)[0].lower()
    if not app.testing and host not in config.TRUSTED_HOSTS:
        abort(400)
    if request.method in {"GET", "HEAD"} and request.endpoint != "healthz":
        current_scheme = _request_scheme()
        canonical_path = _canonical_path(request.path)
        if canonical_path != request.path or (
            host in config.TRUSTED_HOSTS
            and (host != CANONICAL_HOST or current_scheme != CANONICAL_SCHEME)
        ):
            return redirect(_canonical_request_url(canonical_path), code=301)
    restore_remembered_login()
    # Apply revocation, expiry, active-state and role changes before public or
    # protected route functions can consume stale session data.
    refresh_current_session()


@app.after_request
def apply_security_headers(response):
    nonce = getattr(g, "csp_nonce", "")
    frame_sources = "https://www.googletagmanager.com"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "; ".join((
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}' https://www.googletagmanager.com",
        "script-src-attr 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "font-src 'self' https://cdn.jsdelivr.net data:",
        "img-src 'self' data: https://www.google-analytics.com https://www.googletagmanager.com "
        "https://lh3.googleusercontent.com",
        "connect-src 'self' https://www.google-analytics.com https://analytics.google.com "
        "https://region1.google-analytics.com https://www.googletagmanager.com",
        f"frame-src {frame_sources}",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "upgrade-insecure-requests",
    ))
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    )
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if session.get("user_id"):
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
    rotated_remember_cookie = getattr(g, "remember_cookie_value", None)
    if rotated_remember_cookie:
        response.set_cookie(
            "casino_in_remember", rotated_remember_cookie,
            max_age=config.REMEMBER_LOGIN_DAYS * 86400,
            secure=True, httponly=True, samesite="Lax", path="/",
        )
    elif getattr(g, "clear_remember_cookie", False):
        response.delete_cookie(
            "casino_in_remember", secure=True, httponly=True,
            samesite="Lax", path="/",
        )
    return response


@app.after_request
def localize_response(response):
    """Translate rendered UI while leaving stored Korean source data untouched."""

    locale = getattr(g, "locale", "ko")
    response.headers["Content-Language"] = locale
    if locale == "ko" or response.direct_passthrough:
        return response

    content_type = response.headers.get("Content-Type", "")
    if content_type.startswith("text/html"):
        rendered_html = response.get_data(as_text=True)
        endpoint = request.endpoint or ""
        now = time.monotonic()
        if (
            request.method == "GET"
            and endpoint in LOCALIZATION_DISCOVERY_ENDPOINTS
            and now - _localization_render_scan_at.get(endpoint, 0.0) >= 3600
        ):
            try:
                candidates = [
                    text for text in extract_translatable_html_strings(rendered_html)
                    if re.search(r"[\uac00-\ud7a3]", str(translate_text(text, locale)))
                ]
                if candidates:
                    connection = dashboard_db()
                    try:
                        localization_management.register_rendered_strings(
                            connection,
                            candidates,
                            page=endpoint,
                            source_path=request.path,
                        )
                    finally:
                        connection.close()
                _localization_render_scan_at[endpoint] = now
            except Exception:
                logger.exception("Public localization discovery failed for %s", endpoint)
        response.set_data(translate_html(rendered_html, locale))
    elif content_type.startswith("application/json"):
        payload = response.get_json(silent=True)
        if payload is not None:
            response.set_data(
                json.dumps(
                    translate_structure(payload, locale),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            response.mimetype = "application/json"
    return response


@app.after_request
def monitor_security_events(response):
    """Keep failed/probing requests even when the visitor is not signed in."""
    if request.endpoint in {"static", "healthz"}:
        return response
    if not security_monitor.should_inspect(response):
        return response
    connection = dashboard_db()
    try:
        security_monitor.inspect_response(connection, response)
        connection.commit()
    except Exception:
        connection.rollback()
        logger.exception("보안 요청 탐지 기록 실패")
    finally:
        connection.close()
    return response


@app.after_request
def log_user_activity(response):
    """회원과 비회원의 화면 활동을 민감정보 없이 영구 제한과 함께 기록한다."""

    endpoint = request.endpoint
    # Do not append to the table while paging through that same table; otherwise
    # OFFSET pagination would shift between page 1 and page 2.
    if endpoint in {"static", "healthz"}:
        return response
    if endpoint == "auth.admin_logs" and response.status_code == 200:
        return response

    authenticated = bool(session.get("user_id"))
    # 비회원의 폼 제출은 로그인/가입 공격 로그에서 별도로 다룬다. 여기서는
    # 공개 화면 탐색만 남겨 중복 기록과 요청 본문 노출 가능성을 없앤다.
    if not authenticated and request.method not in {"GET", "HEAD"}:
        return response

    global _last_activity_log_retention_cleanup
    connection = dashboard_db()
    try:
        path = f"{request.script_root}{request.path}"[:500]
        resource_id = (path if not authenticated else (endpoint or path))[:200]
        if not authenticated:
            current = now_kst()
            dedupe_since = (
                current - timedelta(minutes=ANONYMOUS_ACTIVITY_DEDUPE_MINUTES)
            ).isoformat(timespec="seconds")
            day_since = (current - timedelta(days=1)).isoformat(timespec="seconds")
            ip_address = security_audit.client_ip()
            duplicate = connection.execute(
                """
                SELECT 1 FROM security_audit_log
                WHERE username='anonymous' AND COALESCE(ip_address, '')=?
                  AND action='PAGE_VIEW' AND resource_type='endpoint'
                  AND resource_id=? AND created_at>=?
                LIMIT 1
                """,
                (ip_address, resource_id, dedupe_since),
            ).fetchone()
            per_ip_count = connection.execute(
                """
                SELECT COUNT(*) FROM security_audit_log
                WHERE username='anonymous' AND COALESCE(ip_address, '')=?
                  AND created_at>=?
                """,
                (ip_address, day_since),
            ).fetchone()[0]
            global_count = connection.execute(
                """
                SELECT COUNT(*) FROM security_audit_log
                WHERE username='anonymous' AND created_at>=?
                """,
                (day_since,),
            ).fetchone()[0]
            if (
                duplicate
                or per_ip_count >= ANONYMOUS_ACTIVITY_PER_IP_DAILY_LIMIT
                or global_count >= ANONYMOUS_ACTIVITY_GLOBAL_DAILY_LIMIT
            ):
                return response
        elif request.method in {"GET", "HEAD"}:
            dedupe_since = (
                now_kst() - timedelta(minutes=AUTHENTICATED_ACTIVITY_DEDUPE_MINUTES)
            ).isoformat(timespec="seconds")
            duplicate = connection.execute(
                """
                SELECT 1 FROM security_audit_log
                WHERE user_id=? AND action='PAGE_VIEW'
                  AND resource_type='endpoint' AND resource_id=?
                  AND created_at>=?
                LIMIT 1
                """,
                (session.get("user_id"), resource_id, dedupe_since),
            ).fetchone()
            if duplicate:
                return response

        security_audit.log_event(
            connection,
            "PAGE_VIEW" if request.method in {"GET", "HEAD"} else "USER_ACTION",
            "endpoint",
            resource_id,
            {
                "endpoint": endpoint,
                "method": request.method,
                "path": path,
                "locale": getattr(g, "locale", "ko"),
                "status_code": response.status_code,
            },
            # A redirect to the login screen is not a successful resource
            # access.  Keep the actual status in detail_json as well.
            success=200 <= response.status_code < 300,
        )
        cleanup_tick = time.monotonic()
        if cleanup_tick - _last_activity_log_retention_cleanup >= 3600:
            # Retention cleanup is maintenance, not part of every page view.
            queries.purge_logs_older_than(connection, days=30)
            _last_activity_log_retention_cleanup = cleanup_tick
        connection.commit()
    except Exception:
        logger.exception("사용자 활동 로그 저장 실패")
    finally:
        connection.close()
    return response


@app.before_request
def purge_expired_account_withdrawals():
    """Anonymize expired withdrawn accounts at most once per worker per hour."""

    global _last_account_retention_cleanup
    current_tick = time.monotonic()
    if current_tick - _last_account_retention_cleanup < 3600:
        return None
    connection = dashboard_db()
    try:
        purged = queries.purge_expired_withdrawn_users(connection)
        if purged:
            logger.info("만료된 탈퇴 계정 개인정보 익명화 완료: %s건", purged)
            if session.get("user_id"):
                current = connection.execute(
                    "SELECT is_active FROM dashboard_users WHERE id=?",
                    (session["user_id"],),
                ).fetchone()
                if not current or not current["is_active"]:
                    session.clear()
        _last_account_retention_cleanup = current_tick
    except Exception:
        logger.exception("탈퇴 계정 보관기간 정리 실패")
    finally:
        connection.close()
    return None


@app.before_request
def enforce_menu_permission():
    if not session.get("user_id"):
        return None
    approved_download_endpoints = {
        "official_docs.import_excel_template",
        "official_docs.export_excel",
    }
    if request.endpoint in approved_download_endpoints:
        connection = dashboard_db()
        try:
            account = connection.execute(
                """SELECT role, is_active, approval_status
                   FROM dashboard_users WHERE id=?""",
                (session["user_id"],),
            ).fetchone()
            allowed = bool(
                account
                and account["is_active"]
                and (
                    account["role"] == "admin"
                    or (
                        account["approval_status"] == "approved"
                        and queries.get_user_permissions(
                            connection, session["user_id"], ("official_docs",)
                        ).get("official_docs", False)
                    )
                )
            )
        finally:
            connection.close()
        if not allowed:
            abort(403)
        return None
    admin_area = (
        request.endpoint in {"paradian_portal_page", "performance_page"}
        or request.blueprint == "official_docs"
    )
    if admin_area:
        connection = dashboard_db()
        try:
            account = connection.execute(
                "SELECT role, is_active FROM dashboard_users WHERE id=?",
                (session["user_id"],),
            ).fetchone()
        finally:
            connection.close()
        if not account or not account["is_active"] or account["role"] != "admin":
            abort(403)
    if request.method in {"GET", "HEAD"} and request.endpoint in PUBLIC_READ_ENDPOINTS:
        return None
    # 공문·자료관리 화면과 변경 작업은 관리자 전용이다. 위에서 명시한
    # 다운로드만 DB 승인 상태와 official_docs 권한을 확인해 일반 사용자에게 허용한다.
    if request.blueprint == "official_docs":
        return None
    permission = (
        "official_docs" if request.blueprint == "official_docs"
        else "tips" if request.blueprint == "tips"
        else ENDPOINT_PERMISSIONS.get(request.endpoint)
    )
    if permission and not current_menu_permissions().get(permission, False):
        abort(403)
    return None

# 뉴스 이슈 카테고리를 경쟁사/정책·규제로 대략 매핑한다(뉴스 프로그램이 이미
# 분류한 issues.category 텍스트에 대한 부분일치 - 정교한 분류는 후속 과제).
COMPETITOR_CATEGORY_KEYWORDS = [
    "파라다이스", "파라다이스시티", "인스파이어", "강원랜드", "세븐럭",
    "그랜드코리아레저", "GKL", "드림타워", "마카오", "싱가포르", "경쟁사",
]
POLICY_CATEGORY_KEYWORDS = [
    "정부 정책", "법률", "규제", "AML", "관광진흥법", "관광진흥개발기금", "정책",
]


@app.context_processor
def inject_globals():
    locale = getattr(g, "locale", "ko")
    role = session.get("role")
    current_user = None
    account_active = not bool(session.get("user_id"))
    localization_pending_count = 0
    if session.get("user_id"):
        cached_user = getattr(g, "current_user_record", None)
        connection = None
        try:
            row = cached_user
            if row is None:
                connection = dashboard_db()
                row = connection.execute(
                    """
                    SELECT id, username, role, name, picture_url, is_active,
                           membership_level
                    FROM dashboard_users WHERE id=?
                    """,
                    (session["user_id"],),
                ).fetchone()
            if row and row["is_active"]:
                account_active = True
                current_user = dict(row)
                role = current_user.get("role") or "user"
                session["role"] = role
                if connection is None:
                    connection = dashboard_db()
                current_user["membership"] = membership.user_grade(
                    connection, current_user["id"], role
                )
                if role == "admin" and request.path.startswith("/admin"):
                    if connection is None:
                        connection = dashboard_db()
                    localization_management.scan_if_due(
                        connection, Path(app.root_path), interval_minutes=60,
                    )
                    localization_pending_count = connection.execute(
                        """SELECT COUNT(*) FROM localization_strings s
                           JOIN localization_languages l
                             ON l.is_active=1 AND l.is_source=0
                           LEFT JOIN localization_translations t
                             ON t.string_id=s.id AND t.language_code=l.language_code
                           WHERE s.deleted_at IS NULL
                             AND (CASE WHEN s.status='Ignored' THEN 'Ignored'
                                  ELSE COALESCE(t.status, 'Pending') END)='Pending'"""
                    ).fetchone()[0]
            elif app.testing and not row:
                # A few legacy unit tests use a session-only fixture.  Never
                # apply this compatibility path in the deployed app.
                account_active = True
            else:
                role = None
        finally:
            if connection is not None:
                connection.close()
    cached_fonts = site_preferences.get_cached_fonts()
    if cached_fonts is None:
        font_connection = dashboard_db()
        try:
            site_font = site_preferences.get_site_font(font_connection)
            number_font = site_preferences.get_number_font(font_connection)
        finally:
            font_connection.close()
    else:
        site_font, number_font = cached_fonts
    endpoint_menu_names = {
        "public_home": "홈",
        "dashboard_home": "홈",
        "action_items_page": "버그 및 건의",
        "create_action_item_route": "버그 및 건의",
        "action_item_detail": "버그 및 건의",
        "community_board_page": "자유 게시판",
        "create_community_post_route": "자유 게시판",
        "notice_board_page": "공지사항",
        "diary_board_page": "나의 일기장",
        "diary_entry_page": "나의 일기장",
        "edit_diary_entry_route": "나의 일기장",
        "create_notice_post_route": "공지사항",
        "community_post_page": "자유 게시판",
        "admin_action_items_page": "미처리 과제",
        "create_admin_action_item_route": "미처리 과제",
        "performance_page": "경영실적",
        "paradian_portal_page": "관리자 전용",
        "related_news_page": "국내 뉴스",
        "overseas_news_page": "해외 뉴스",
        "market_trend_page": "주가 정보",
        "tourism_trend_page": "관광객 추이",
        "economic_trend_page": "환율·유가",
        "holiday_calendar_page": "나라별 연휴",
        "salary_trend_page": "연봉·평점",
        "recruitment_page": "채용정보",
        "company_recruitment_guide_page": "족보",
        "source_download_page": "원천 데이터 다운",
        "casino_industry_page": "국내 카지노 산업",
        "casino_insights_page": "카지노 인사이트",
        "casino_market_share_page": "산업 M/S",
        "casino_visitors_page": "연도별 카지노 이용객",
        "casino_revenue_page": "연도별 카지노 매출액 비율",
        "casino_fund_page": "기금 부과 현황",
        "disclosures_page": "기업별 공시",
        "upload_ir_document": "기업별 공시",
        "download_ir_document": "기업별 공시",
        "reanalyze_ir_document": "기업별 공시",
        "delete_ir_document": "기업별 공시",
        "laws_page": "법률·규제",
        "legislation_page": "입법동향",
        "fund_increase_scenario_page": "기금인상 시나리오",
        "companies_page": "주요 국내기업",
        "company_comparison_page": "기업 비교",
        "company_expert_page": "전문정보",
        "company_benefits_page": "복리후생",
        "company_news_page": "기업별 뉴스",
        "research_library_page": "기업별 리포트",
        "download_research_document": "기업별 리포트",
        "reanalyze_research_document": "기업별 리포트",
        "update_research_document_title": "기업별 리포트",
        "delete_research_document": "기업별 리포트",
        "unified_search_page": "통합검색",
        "sitemap_page": "사이트맵",
        "credits_page": "사이트 안내",
        "credits_management_page": "출처 관리",
        "create_credit_source_route": "출처 관리",
        "edit_credit_source_route": "출처 관리",
        "hide_credit_source_route": "출처 관리",
        "auth.my_account": "내 계정",
        "auth.login": "로그인",
        "auth.register": "가입 신청",
        "auth.user_management": "관리자 페이지",
        "auth.membership_management": "회원관리",
        "auth.membership_user_detail": "회원관리",
        "auth.ai_settings": "API 설정",
        "auth.admin_logs": "관리자 로그",
        "auth.admin_tasks": "자동화 작업 현황",
        "auth.localization_dashboard": "Localization",
        "auth.localization_qa": "Localization QA",
    }
    if request.blueprint == "official_docs":
        current_menu_name = "공문·자료관리"
    elif request.blueprint == "tips":
        current_menu_name = "자료실"
    else:
        current_menu_name = endpoint_menu_names.get(
            request.endpoint, "Management Dashboard"
        )
    current_menu_name = translate_text(current_menu_name, locale)
    switch_paths = alternate_paths(
        request.path, request.query_string.decode("utf-8", errors="ignore")
    )
    catalog = load_catalog()
    seo_defaults = _seo_defaults()
    return {
        "current_username": session.get("username") if account_active else None,
        "current_user": current_user,
        "now_str": today_kst_str(),
        "current_user_role": role if account_active and role else "anonymous",
        "site_font": site_font,
        "number_font": number_font,
        "menu_permissions": current_menu_permissions(),
        "localization_pending_count": localization_pending_count,
        "csp_nonce": getattr(g, "csp_nonce", ""),
        "global_csrf_token": get_csrf_token(),
        "current_menu_name": current_menu_name,
        "display_y_drive_path": display_y_drive_path,
        "current_locale": locale,
        "locale_prefix": "" if locale == "ko" else f"/{locale.lower()}",
        "locale_options": (
            {"code": "ko", "label": "KO", "name": "한국어"},
            {"code": "en", "label": "EN", "name": "English"},
            {"code": "ja", "label": "JA", "name": "日本語"},
            {"code": "yue-HK", "label": "YUE", "name": "廣東話"},
        ),
        "locale_urls": switch_paths,
        "canonical_url": seo_defaults["seo_canonical_url"],
        "hreflang_urls": seo_defaults["seo_hreflang_urls"],
        "localized_meta": meta_for(locale),
        "i18n_catalog": catalog if locale == "en" else {},
        "t": lambda value: translate_text(value, locale),
        "t_source": lambda value: translate_source_label(value, locale),
        **seo_defaults,
    }


def _site_map_links():
    """현재 로그인 상태와 메뉴 권한에 맞는 사이트맵 링크를 반환한다."""
    account_active = False
    active_role = None
    if session.get("user_id"):
        connection = dashboard_db()
        try:
            account = connection.execute(
                "SELECT role, is_active FROM dashboard_users WHERE id=?",
                (session["user_id"],),
            ).fetchone()
        finally:
            connection.close()
        if account:
            account_active = bool(account["is_active"])
            active_role = account["role"] if account_active else None
        elif app.testing:
            account_active = True
            active_role = session.get("role")
    links = [
        {
            "label": "홈",
            "description": "Casino IN 시작 화면",
            "endpoint": "public_home",
        },
        {
            "label": "뉴스",
            "description": "국내외 카지노·관광 산업 뉴스",
            "endpoint": "related_news_page",
            "children": [
                {"label": "국내 뉴스", "endpoint": "related_news_page"},
                {"label": "해외 뉴스", "endpoint": "overseas_news_page"},
            ],
        },
        {
            "label": "시장 정보",
            "description": "카지노 산업·관광객·시장 지표",
            "endpoint": "casino_industry_page",
            "children": [
                {"label": "국내 카지노 산업", "endpoint": "casino_industry_page"},
                {"label": "카지노 인사이트", "endpoint": "casino_insights_page"},
                {"label": "산업 M/S", "endpoint": "casino_market_share_page"},
                {"label": "연도별 카지노 이용객", "endpoint": "casino_visitors_page"},
                {"label": "연도별 카지노 매출액 비율", "endpoint": "casino_revenue_page"},
                {"label": "기금 부과 현황", "endpoint": "casino_fund_page"},
                {"label": "주가 정보", "endpoint": "market_trend_page"},
                {"label": "관광객 추이", "endpoint": "tourism_trend_page"},
                {"label": "환율·유가", "endpoint": "economic_trend_page"},
                {"label": "나라별 연휴", "endpoint": "holiday_calendar_page"},
            ],
        },
        {
            "label": "기업정보",
            "description": "국내 주요 기업 뉴스·공시·리포트",
            "endpoint": "companies_page",
            "children": [
                {"label": "주요 국내기업", "endpoint": "companies_page"},
                {"label": "기업 비교", "endpoint": "company_comparison_page"},
                {"label": "전문정보", "endpoint": "company_expert_page"},
                {"label": "복리후생", "endpoint": "company_benefits_page"},
                {"label": "기업별 뉴스", "endpoint": "company_news_page"},
                {"label": "기업별 공시", "endpoint": "disclosures_page"},
                {"label": "기업별 리포트", "endpoint": "research_library_page"},
                {"label": "연봉·평점", "endpoint": "salary_trend_page"},
                {"label": "채용정보", "endpoint": "recruitment_page"},
                {"label": "족보", "endpoint": "company_recruitment_guide_page"},
            ],
        },
        {
            "label": "법률·규제",
            "description": "현행 법령과 입법 동향",
            "endpoint": "laws_page",
            "children": [
                {"label": "법령", "endpoint": "laws_page"},
                {"label": "입법동향", "endpoint": "legislation_page"},
                {"label": "기금인상 시나리오", "endpoint": "fund_increase_scenario_page"},
            ],
        },
        {
            "label": "자료실",
            "description": "업무 자료·관련 사이트·원천 데이터",
            "endpoint": "tips.list_page",
            "children": [
                {"label": "자료실", "endpoint": "tips.list_page"},
                {"label": "관련 사이트", "endpoint": "tips.sites_page"},
                {"label": "카지노 용어집", "endpoint": "tips.glossary_page"},
                {
                    "label": "원천 데이터 다운",
                    "endpoint": "source_download_page",
                    "locked": not account_active,
                },
            ],
        },
        {
            "label": "게시판",
            "description": "자유 게시판, 공지사항과 버그 및 건의",
            "endpoint": "community_board_page",
            "children": [
                {"label": "자유 게시판", "endpoint": "community_board_page"},
                {"label": "공지사항", "endpoint": "notice_board_page"},
                {"label": "버그 및 건의", "endpoint": "action_items_page"},
            ],
        },
        {
            "label": "통합검색",
            "description": "뉴스·공시·법령·자료 검색",
            "endpoint": "unified_search_page",
        },
        {
            "label": "사이트 안내",
            "description": "대표 데이터 출처, 이용 안내와 회원등급",
            "endpoint": "credits_page",
        },
    ]
    if not account_active:
        links.extend([
            {"label": "로그인", "description": "대시보드 계정으로 접속", "endpoint": "auth.login"},
            {"label": "가입 신청", "description": "새 계정 승인 요청", "endpoint": "auth.register"},
        ])
        return links
    links.append({
        "label": "내 계정",
        "description": "프로필과 로그인·보안 설정",
        "endpoint": "auth.my_account",
    })
    if active_role == "admin":
        links.append({
            "label": "관리자 전용",
            "description": "사이트·계정·공문·경영실적 관리",
            "endpoint": "paradian_portal_page",
            "children": [
                {"label": "관리자 페이지", "endpoint": "auth.user_management"},
                {"label": "회원관리", "endpoint": "auth.membership_management"},
                {"label": "API 설정", "endpoint": "auth.ai_settings"},
                {"label": "로그", "endpoint": "auth.admin_logs"},
                {"label": "자동화 작업", "endpoint": "auth.admin_tasks"},
                {"label": "Localization", "endpoint": "auth.localization_dashboard"},
                {"label": "미처리 과제", "endpoint": "admin_action_items_page"},
                {"label": "공문·자료관리", "endpoint": "official_docs.dashboard"},
                {"label": "경영 실적", "endpoint": "performance_page"},
            ],
        })
    return links


@app.route("/sitemap")
def sitemap_page():
    return render_template("sitemap.html", site_map_links=_site_map_links())


def _sitemap_url_entry(path, lastmod=None):
    urls = _alternate_absolute_urls(path)
    alternates = {**urls, "x-default": urls["ko"]}
    date_value = _date_only(lastmod)
    entries = []
    for locale in SUPPORTED_LOCALES:
        entries.append({
            "loc": urls[locale],
            "lastmod": date_value,
            "alternates": alternates,
        })
    return entries


def _build_sitemap_entries(connection):
    entries = []
    try:
        news_lastmod = news_reader.last_updated_at()
    except Exception:
        logger.warning("사이트맵 뉴스 최신시각 조회 실패", exc_info=True)
        news_lastmod = None
    static_lastmods = {
        "public_home": max(
            filter(
                None,
                (
                    news_lastmod,
                    _max_timestamp(connection, "law_updates", "fetched_at"),
                    _max_timestamp(connection, "dart_disclosures", "fetched_at"),
                ),
            ),
            default=None,
        ),
        "related_news_page": news_lastmod,
        "overseas_news_page": _max_timestamp(connection, "overseas_news_articles", "collected_at"),
        "market_trend_page": _max_timestamp(connection, "market_quotes", "fetched_at"),
        "tourism_trend_page": _max_timestamp(connection, "tourism_visitor_stats", "fetched_at"),
        "economic_trend_page": _max_timestamp(connection, "economic_series", "fetched_at"),
        "salary_trend_page": _max_timestamp(connection, "salary_snapshots", "fetched_at"),
        "recruitment_page": _max_timestamp(connection, "recruitment_jobs", "last_seen_at"),
        "company_recruitment_guide_page": _max_timestamp(
            connection, "company_recruitment_guides", "updated_at"
        ),
        "disclosures_page": _max_timestamp(connection, "dart_disclosures", "fetched_at"),
        "laws_page": _max_timestamp(connection, "law_updates", "fetched_at"),
        "legislation_page": max(
            filter(
                None,
                (
                    _max_timestamp(connection, "legislative_bills", "updated_at"),
                    _max_timestamp(
                        connection,
                        "government_legislative_notices",
                        "updated_at",
                    ),
                ),
            ),
            default=None,
        ),
        "companies_page": max(
            filter(
                None,
                (
                    _max_timestamp(connection, "company_research_profiles", "updated_at"),
                    _max_timestamp(connection, "research_documents", "updated_at"),
                ),
            ),
            default=None,
        ),
        "company_benefits_page": _max_timestamp(
            connection, "company_benefits", "updated_at"
        ),
        "company_news_page": news_lastmod,
        "research_library_page": _max_timestamp(connection, "research_documents", "updated_at"),
        "tips.list_page": _max_timestamp(connection, "tips_articles", "updated_at", "is_deleted=0 AND draft=0"),
        "tips.sites_page": _max_timestamp(connection, "related_sites", "updated_at", "is_deleted=0 AND is_public=1"),
        "tips.glossary_page": _max_timestamp(connection, "casino_glossary_terms", "updated_at", "is_deleted=0 AND is_public=1"),
        "credits_page": max(
            filter(
                None,
                (
                    _max_timestamp(connection, "dashboard_analysis_runs", "finished_at"),
                    _max_timestamp(connection, "tips_articles", "updated_at", "is_deleted=0 AND draft=0"),
                ),
            ),
            default=None,
        ),
    }
    for endpoint in SITEMAP_STATIC_ENDPOINTS:
        entries.extend(
            _sitemap_url_entry(
                _neutral_url_for(endpoint),
                static_lastmods.get(endpoint),
            )
        )

    try:
        tip_rows = connection.execute(
            """
            SELECT slug, updated_at, published_date
            FROM tips_articles
            WHERE is_deleted=0 AND draft=0
              AND slug IS NOT NULL AND TRIM(slug)<>''
            ORDER BY published_date DESC, created_at DESC
            """
        ).fetchall()
    except sqlite3.Error:
        logger.warning("사이트맵 공개 자료 조회 실패", exc_info=True)
        tip_rows = []
    for row in tip_rows:
        try:
            entries.extend(
                _sitemap_url_entry(
                    _neutral_url_for("tips.detail_page", slug=row["slug"]),
                    row["updated_at"] or row["published_date"],
                )
            )
        except (TypeError, ValueError):
            logger.warning("사이트맵 자료 URL 생성 실패 slug=%r", row["slug"])
    return entries


@app.route("/robots.txt")
def robots_txt():
    lines = ["User-agent: *", "Allow: /", ""]
    protected_paths = (
        "/admin", "/login", "/logout", "/register", "/api/",
        "/official-docs/", "/board",
    )
    for locale_prefix in ("", "/en", "/ja", "/yue-hk"):
        lines.extend(
            f"Disallow: {locale_prefix}{path}" for path in protected_paths
        )
    lines.extend(("", f"Sitemap: {SITEMAP_PUBLIC_URL}/sitemap.xml"))
    return app.response_class("\n".join(lines), mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    connection = dashboard_db()
    try:
        entries = _build_sitemap_entries(connection)
    finally:
        connection.close()
    urlset = Element(f"{{{SITEMAP_NAMESPACE}}}urlset")
    for entry in entries:
        url_node = SubElement(urlset, f"{{{SITEMAP_NAMESPACE}}}url")
        SubElement(url_node, f"{{{SITEMAP_NAMESPACE}}}loc").text = entry["loc"]
        if entry["lastmod"]:
            SubElement(url_node, f"{{{SITEMAP_NAMESPACE}}}lastmod").text = entry["lastmod"]
        for language_code, href in entry["alternates"].items():
            SubElement(
                url_node,
                f"{{{XHTML_NAMESPACE}}}link",
                {"rel": "alternate", "hreflang": language_code, "href": href},
            )
    xml = tostring(urlset, encoding="utf-8", xml_declaration=True)
    response = app.response_class(
        xml, content_type="application/xml; charset=utf-8"
    )
    response.headers["Cache-Control"] = "public, max-age=900"
    return response


@app.route("/rss.xml")
def rss_xml():
    connection = dashboard_db()
    try:
        items = rss_feed.build_public_items(connection, SITEMAP_PUBLIC_URL)
    finally:
        connection.close()
    response = app.response_class(
        rss_feed.render(items, SITEMAP_PUBLIC_URL),
        content_type="application/rss+xml; charset=utf-8",
    )
    response.headers["Cache-Control"] = "public, max-age=900"
    return response


def _max_timestamp(connection, table, column, where_clause="", params=()):
    query = f"SELECT MAX({column}) AS value FROM {table}"
    if where_clause:
        query += f" WHERE {where_clause}"
    try:
        row = connection.execute(query, params).fetchone()
    except Exception:
        logger.warning("최신시각 조회 실패: %s.%s", table, column, exc_info=True)
        return None
    return row["value"] if row and row["value"] else None


def _format_minute(value):
    if not value:
        return None
    return official_document_manager.datetime_minute(value)


def _parse_iso_timestamp(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _latest_timestamp_from_rows(rows, key, predicate=None):
    values = []
    for row in rows:
        if predicate and not predicate(row):
            continue
        value = row.get(key)
        if value:
            values.append(value)
    return max(values) if values else None


def _market_freshness(quotes):
    is_global = lambda row: row.get("asset_type") == "global_stock"
    is_domestic = lambda row: row.get("asset_type") != "global_stock"
    return {
        "domestic_checked_at": _latest_timestamp_from_rows(quotes, "fetched_at", is_domestic),
        "global_checked_at": _latest_timestamp_from_rows(quotes, "fetched_at", is_global),
        "domestic_base_date": _latest_timestamp_from_rows(quotes, "base_date", is_domestic),
        "global_base_date": _latest_timestamp_from_rows(quotes, "base_date", is_global),
        "checked_at": _latest_timestamp_from_rows(quotes, "fetched_at"),
    }


def _economic_freshness(series):
    oil = [item for item in series if item.get("category") == "oil"]
    exchange = [item for item in series if item.get("category") == "exchange"]
    return {
        "oil_checked_at": _latest_timestamp_from_rows(oil, "fetched_at"),
        "oil_changed_at": _latest_timestamp_from_rows(oil, "changed_at"),
        "exchange_checked_at": _latest_timestamp_from_rows(exchange, "fetched_at"),
        "exchange_changed_at": _latest_timestamp_from_rows(exchange, "changed_at"),
        "checked_at": _latest_timestamp_from_rows(series, "fetched_at"),
        "changed_at": _latest_timestamp_from_rows(series, "changed_at"),
    }


def _timestamp_is_stale(value, *, max_age_hours=None, max_age_minutes=None):
    timestamp = _parse_iso_timestamp(value)
    if timestamp is None:
        return True
    if max_age_minutes is not None:
        threshold = timedelta(minutes=max_age_minutes)
    else:
        threshold = timedelta(hours=max_age_hours or 0)
    return datetime.now(config.KST) - timestamp >= threshold


def _refresh_market_quotes_if_needed(connection):
    quotes = queries.list_market_quotes(connection)
    freshness = _market_freshness(quotes)
    domestic_stale = _timestamp_is_stale(
        freshness.get("domestic_checked_at"), max_age_hours=6
    )
    global_stale = queries.global_market_quotes_need_refresh(
        connection, max_age_minutes=10
    )

    if domestic_stale:
        result = market_data.fetch_dashboard_quotes()
        for quote in result["quotes"]:
            queries.upsert_market_quote(connection, quote)
            queries.upsert_market_quote_history(
                connection, quote["symbol"], quote.get("history") or []
            )
        if result["errors"]:
            logger.warning("국내 주가 수동 보정 갱신 중 오류: %s", result["errors"])

    if global_stale:
        global_result = market_data.fetch_global_quotes()
        for quote in global_result["quotes"]:
            queries.upsert_market_quote(connection, quote)
            queries.upsert_market_quote_history(
                connection, quote["symbol"], quote.get("history") or []
            )
        for failure in global_result["errors"]:
            queries.mark_market_quote_failure(
                connection, failure.get("symbol"), failure.get("error")
            )
        if global_result["errors"]:
            logger.warning(
                "해외 주가 수동 보정 갱신 중 오류: %s",
                [item.get("error") for item in global_result["errors"]],
            )

    if domestic_stale or global_stale:
        quotes = queries.list_market_quotes(connection)
    return quotes


def _refresh_economic_series_if_needed(connection):
    series = queries.list_economic_series(connection)
    freshness = _economic_freshness(series)
    if not _timestamp_is_stale(freshness.get("checked_at"), max_age_hours=12):
        return series

    results = (economic_data.fetch_oil(), economic_data.fetch_exchange())
    items = [item for result in results for item in result["items"]]
    errors = [error for result in results for error in result["errors"]]
    for item in items:
        queries.upsert_economic_observation(connection, item)
    if errors:
        logger.warning("유가·환율 수동 보정 갱신 중 오류: %s", errors[:10])
    return queries.list_economic_series(connection)


def _legacy_credits_rows(connection):
    rows = []

    def push(
        menu,
        dataset,
        source_name,
        source_url,
        cadence,
        checked_at=None,
        changed_at=None,
        notes="",
    ):
        rows.append({
            "menu": menu,
            "dataset": dataset,
            "source_name": source_name,
            "source_url": source_url,
            "cadence": cadence,
            "checked_at": _format_minute(checked_at),
            "changed_at": _format_minute(changed_at),
            "notes": notes,
        })

    news_updated_at = news_reader.last_updated_at()
    push(
        "뉴스",
        "카지노 관련 뉴스",
        "news_history.db / AI 이슈 요약 아카이브",
        "",
        "외부 수집 DB 반영 주기에 따름",
        checked_at=news_updated_at,
        changed_at=news_updated_at,
        notes="대시보드는 읽기 전용으로 연동하며, 원본 뉴스 DB의 최종 수집 시각을 표시합니다.",
    )

    overseas_state = overseas_news.sync_state(connection)
    push(
        "뉴스",
        "마카오·일본 해외 뉴스 / 한글 번역",
        "Google News RSS 검색 결과 / OpenAI 번역",
        "https://news.google.com/",
        "매일 자동 수집·번역",
        checked_at=overseas_state.get("last_checked_at"),
        changed_at=overseas_state.get("last_changed_at"),
        notes="기사 제목·언론사·발행일·원문 링크를 저장하며 기사 전문은 복제하지 않습니다.",
    )

    dart_freshness = queries.get_data_freshness(
        connection, "dart_disclosures", "dart_sync", "fetched_at"
    )
    push(
        "기업정보",
        "DART 공시 / AI 요약",
        "금융감독원 DART",
        "https://dart.fss.or.kr/",
        "매일 정기 동기화",
        checked_at=dart_freshness.get("checked_at"),
        changed_at=dart_freshness.get("changed_at"),
        notes="관심 기업 공시 원문과 저장된 AI 분석 결과를 함께 표시합니다.",
    )

    law_sync = queries.get_latest_completed_run(connection, "law_sync")
    law_checked_at = (law_sync or {}).get("finished_at")
    push(
        "법률·규제",
        "국가법령정보",
        "국가법령정보센터",
        "https://www.law.go.kr/",
        "매일 정기 동기화",
        checked_at=law_checked_at,
        changed_at=_max_timestamp(connection, "law_updates", "fetched_at"),
        notes="법령 본문, 변경 이력, AI 요약을 모니터링합니다.",
    )
    push(
        "법률·규제",
        "국회 의안정보",
        "국회 열린국회정보 Open API",
        "https://open.assembly.go.kr/portal/openapi/ALLBILLV2",
        "매일 정기 동기화",
        checked_at=law_checked_at,
        changed_at=_max_timestamp(connection, "legislative_bills", "updated_at"),
        notes="카지노 관련 입법을 필터링하고 산업 영향도를 함께 저장합니다.",
    )
    push(
        "법률·규제",
        "정부입법예고",
        "법제처 국민참여입법센터",
        "https://opinion.lawmaking.go.kr/",
        "매일 정기 동기화",
        checked_at=law_checked_at,
        changed_at=_max_timestamp(connection, "government_legislative_notices", "updated_at"),
        notes="정부입법예고와 첨부자료 링크를 함께 관리합니다.",
    )

    market_quotes = queries.list_market_quotes(connection)
    market_freshness = _market_freshness(market_quotes)
    push(
        "시장 정보",
        "국내 주가·지수",
        "공공데이터포털 API",
        "https://www.data.go.kr/",
        "배치 + 화면 진입 시 자동 확인",
        checked_at=market_freshness.get("domestic_checked_at"),
        changed_at=market_freshness.get("domestic_checked_at"),
        notes="국내 4개 카지노 기업과 KOSPI를 자동 확인하며, 오래된 시세는 페이지 진입 시 즉시 재조회합니다.",
    )
    push(
        "시장 정보",
        "해외 주가",
        "Yahoo Finance",
        "https://finance.yahoo.com/",
        "10분 캐시 기준 자동 갱신",
        checked_at=market_freshness.get("global_checked_at"),
        changed_at=market_freshness.get("global_checked_at"),
        notes="마카오 주요 카지노 운영사 4개 종목을 자동 갱신하며, 실패 시 마지막 정상값을 유지합니다.",
    )

    tourism_freshness = queries.get_data_freshness(
        connection, "tourism_visitor_stats", "tourism_stats_sync"
    )
    push(
        "시장 정보",
        "관광객 추이",
        "한국문화관광연구원 출입국관광통계서비스 API",
        "http://openapi.tour.go.kr/",
        "매일 정기 동기화",
        checked_at=tourism_freshness.get("checked_at"),
        changed_at=tourism_freshness.get("changed_at"),
        notes="국가별 방한 관광객 수와 예측치를 함께 시각화합니다.",
    )

    economic_freshness = _economic_freshness(queries.list_economic_series(connection))
    push(
        "시장 정보",
        "유가정보",
        "한국석유공사 Opinet",
        "https://www.opinet.co.kr/",
        "배치 + 화면 진입 시 자동 갱신",
        checked_at=economic_freshness.get("oil_checked_at"),
        changed_at=economic_freshness.get("oil_changed_at"),
        notes="보통휘발유·경유·부탄 평균가를 자동 갱신하며, 오래된 데이터는 화면 진입 시 재수집합니다.",
    )
    push(
        "시장 정보",
        "환율",
        "한국수출입은행 Open API",
        "https://www.koreaexim.go.kr/",
        "배치 + 화면 진입 시 자동 갱신",
        checked_at=economic_freshness.get("exchange_checked_at"),
        changed_at=economic_freshness.get("exchange_changed_at"),
        notes="USD·JPY·CNH·EUR 기준 환율을 자동 갱신하며, 오래된 데이터는 화면 진입 시 재수집합니다.",
    )

    salary_sync = queries.get_latest_completed_run(connection, "salary_sync")
    push(
        "기업정보",
        "연봉",
        "잡코리아 / OpenBizData",
        "https://www.jobkorea.co.kr/",
        "매일 정기 동기화",
        checked_at=(salary_sync or {}).get("finished_at"),
        changed_at=_max_timestamp(connection, "salary_snapshots", "fetched_at"),
        notes="카지노 4사와 업계 비교 기준을 월별 스냅샷으로 누적합니다.",
    )

    recruitment_sync = queries.get_latest_completed_run(connection, "recruitment_sync")
    push(
        "기업정보",
        "채용",
        "잡코리아 / 사람인 / 인크루트",
        "https://www.jobkorea.co.kr/",
        "매일 정기 동기화",
        checked_at=(recruitment_sync or {}).get("finished_at"),
        changed_at=_max_timestamp(connection, "recruitment_jobs", "last_seen_at"),
        notes="AI가 고용형태, 처우, 확인 필요 사항을 카드형으로 요약합니다.",
    )

    push(
        "기업정보",
        "업로드 PDF 분석 자료",
        "사용자 업로드 원문 + AI 추출",
        "",
        "등록/재분석 시 즉시 반영",
        checked_at=_max_timestamp(connection, "research_documents", "analyzed_at"),
        changed_at=_max_timestamp(connection, "research_documents", "updated_at"),
        notes="제목은 직접 입력값 우선, 비우면 GPT 제안 제목을 우선 적용합니다.",
    )

    push(
        "자료실",
        "업무 자료 게시판",
        "관리자/사용자 직접 작성",
        "",
        "저장 즉시 반영",
        checked_at=_max_timestamp(connection, "tips_articles", "updated_at", "is_deleted=0"),
        changed_at=_max_timestamp(connection, "tips_articles", "updated_at", "is_deleted=0"),
        notes="Markdown, 코드블록, 목차, 첨부파일, 댓글 기능을 지원합니다.",
    )

    push(
        "자료실",
        "관련 사이트 링크",
        "관리자 등록 링크 아카이브",
        "",
        "저장 즉시 반영",
        checked_at=_max_timestamp(connection, "related_sites", "updated_at", "is_deleted=0"),
        changed_at=_max_timestamp(connection, "related_sites", "updated_at", "is_deleted=0"),
        notes="카테고리별 외부 사이트와 설명을 함께 정리합니다.",
    )

    push(
        "관리자 전용",
        "공문·자료관리",
        "내부 접수 자료 / Y드라이브 연계",
        "",
        "등록 즉시 반영",
        checked_at=_max_timestamp(connection, "official_documents", "updated_at", "is_active=1"),
        changed_at=_max_timestamp(connection, "official_documents", "updated_at", "is_active=1"),
        notes="삭제 자료는 즉시 물리 삭제하지 않고 보존 정책에 따라 관리합니다.",
    )

    push(
        "관리자 전용",
        "경영 실적",
        "텔레그램 성과 메시지 수집",
        "",
        "메시지 수신 / 수집 작업 기준",
        checked_at=_max_timestamp(connection, "performance_reports", "created_at"),
        changed_at=_max_timestamp(connection, "performance_reports", "report_date"),
        notes="성공적으로 수집된 최신 보고 메시지 기준 시각을 표시합니다.",
    )

    return rows


def _credit_freshness(connection):
    news_updated_at = news_reader.last_updated_at()
    overseas_state = overseas_news.sync_state(connection)
    dart_state = queries.get_data_freshness(
        connection, "dart_disclosures", "dart_sync", "fetched_at"
    )
    law_sync = queries.get_latest_completed_run(connection, "law_sync") or {}
    law_checked_at = law_sync.get("finished_at")
    market_state = _market_freshness(queries.list_market_quotes(connection))
    tourism_state = queries.get_data_freshness(
        connection, "tourism_visitor_stats", "tourism_stats_sync"
    )
    economic_state = _economic_freshness(queries.list_economic_series(connection))
    salary_sync = queries.get_latest_completed_run(connection, "salary_sync") or {}
    recruitment_sync = (
        queries.get_latest_completed_run(connection, "recruitment_sync") or {}
    )
    return {
        "domestic_news": (news_updated_at, news_updated_at),
        "overseas_news": (
            overseas_state.get("last_checked_at"),
            overseas_state.get("last_changed_at"),
        ),
        "dart": (dart_state.get("checked_at"), dart_state.get("changed_at")),
        "laws": (
            law_checked_at,
            _max_timestamp(connection, "law_updates", "fetched_at"),
        ),
        "assembly_bills": (
            law_checked_at,
            _max_timestamp(connection, "legislative_bills", "updated_at"),
        ),
        "government_notices": (
            law_checked_at,
            _max_timestamp(
                connection, "government_legislative_notices", "updated_at"
            ),
        ),
        "domestic_market": (
            market_state.get("domestic_checked_at"),
            market_state.get("domestic_checked_at"),
        ),
        "global_market": (
            market_state.get("global_checked_at"),
            market_state.get("global_checked_at"),
        ),
        "tourism": (
            tourism_state.get("checked_at"), tourism_state.get("changed_at")
        ),
        "oil": (
            economic_state.get("oil_checked_at"),
            economic_state.get("oil_changed_at"),
        ),
        "exchange": (
            economic_state.get("exchange_checked_at"),
            economic_state.get("exchange_changed_at"),
        ),
        "salary": (
            salary_sync.get("finished_at"),
            _max_timestamp(connection, "salary_snapshots", "fetched_at"),
        ),
        "recruitment": (
            recruitment_sync.get("finished_at"),
            _max_timestamp(connection, "recruitment_jobs", "last_seen_at"),
        ),
        "research": (
            _max_timestamp(connection, "research_documents", "analyzed_at"),
            _max_timestamp(connection, "research_documents", "updated_at"),
        ),
        "tips": (
            _max_timestamp(
                connection, "tips_articles", "updated_at", "is_deleted=0"
            ),
            _max_timestamp(
                connection, "tips_articles", "updated_at", "is_deleted=0"
            ),
        ),
        "related_sites": (
            _max_timestamp(
                connection, "related_sites", "updated_at", "is_deleted=0"
            ),
            _max_timestamp(
                connection, "related_sites", "updated_at", "is_deleted=0"
            ),
        ),
        "official_docs": (
            _max_timestamp(
                connection, "official_documents", "updated_at", "is_active=1"
            ),
            _max_timestamp(
                connection, "official_documents", "updated_at", "is_active=1"
            ),
        ),
        "performance": (
            _max_timestamp(connection, "performance_reports", "created_at"),
            _max_timestamp(connection, "performance_reports", "report_date"),
        ),
    }


def _credits_rows(connection):
    freshness = _credit_freshness(connection)
    rows = queries.list_credit_sources(connection)
    for row in rows:
        checked_at, changed_at = freshness.get(
            row.get("freshness_key"), (None, None)
        )
        row["checked_at"] = _format_minute(checked_at)
        row["changed_at"] = _format_minute(changed_at)
    return rows


CREDIT_FRESHNESS_OPTIONS = (
    ("", "수동 항목(시각 표시 안 함)"),
    ("domestic_news", "국내 뉴스"),
    ("overseas_news", "해외 뉴스"),
    ("dart", "DART 공시"),
    ("laws", "국가법령정보"),
    ("assembly_bills", "국회 의안"),
    ("government_notices", "정부입법예고"),
    ("domestic_market", "국내 시세"),
    ("global_market", "해외 시세"),
    ("tourism", "관광객 통계"),
    ("oil", "유가"),
    ("exchange", "환율"),
    ("salary", "연봉"),
    ("recruitment", "채용"),
    ("research", "PDF 분석"),
    ("tips", "자료실"),
    ("related_sites", "관련 사이트"),
    ("official_docs", "공문·자료"),
    ("performance", "경영 실적"),
)


def _credit_source_form_values(existing=None):
    values = {
        "menu": " ".join((request.form.get("menu") or "").split()),
        "dataset": " ".join((request.form.get("dataset") or "").split()),
        "source_name": " ".join(
            (request.form.get("source_name") or "").split()
        ),
        "source_url": (request.form.get("source_url") or "").strip(),
        "cadence": " ".join((request.form.get("cadence") or "").split()),
        "freshness_key": (request.form.get("freshness_key") or "").strip(),
        "notes": (request.form.get("notes") or "").strip(),
        "is_active": 1 if request.form.get("is_active") == "1" else 0,
    }
    limits = {
        "menu": 80,
        "dataset": 160,
        "source_name": 200,
        "source_url": 500,
        "cadence": 120,
        "notes": 1000,
    }
    for field in ("menu", "dataset", "source_name", "cadence"):
        if not values[field]:
            raise ValueError("메뉴, 데이터, 출처, 업데이트 주기를 모두 입력해주세요.")
    if any(len(values[field]) > limit for field, limit in limits.items()):
        raise ValueError("입력 가능한 글자 수를 초과했습니다.")
    if values["source_url"]:
        parsed = urlsplit(values["source_url"])
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
        ):
            raise ValueError("출처 URL은 정상적인 HTTP(S) 주소만 입력할 수 있습니다.")
    allowed_freshness = {key for key, _ in CREDIT_FRESHNESS_OPTIONS}
    if values["freshness_key"] not in allowed_freshness:
        raise ValueError("올바른 자동 시각 연동 항목을 선택해주세요.")
    try:
        values["sort_order"] = int(request.form.get("sort_order") or 100)
    except (TypeError, ValueError) as exc:
        raise ValueError("표시 순서는 숫자로 입력해주세요.") from exc
    if not 0 <= values["sort_order"] <= 9999:
        raise ValueError("표시 순서는 0~9999 범위로 입력해주세요.")
    values["source_key"] = (
        existing["source_key"] if existing else f"custom_{secrets.token_hex(8)}"
    )
    return values


@app.get("/admin/credits")
@admin_required
def credits_management_page():
    connection = dashboard_db()
    try:
        return render_template(
            "credits_management.html",
            sources=queries.list_credit_sources(connection, include_inactive=True),
            freshness_options=CREDIT_FRESHNESS_OPTIONS,
            csrf_token=get_csrf_token(),
        )
    finally:
        connection.close()


@app.post("/admin/credits")
@admin_required
def create_credit_source_route():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        try:
            values = _credit_source_form_values()
            values["is_active"] = 1
            source_id = queries.create_credit_source(
                connection, values, session.get("user_id")
            )
        except (ValueError, sqlite3.IntegrityError) as exc:
            connection.rollback()
            flash(str(exc), "error")
        else:
            security_audit.log_event(
                connection, "CREDIT_SOURCE_CREATE", "credit_source", source_id,
                {"dataset": values["dataset"]},
            )
            connection.commit()
            flash("출처 항목을 등록했습니다.", "success")
    finally:
        connection.close()
    return redirect(url_for("credits_management_page"))


@app.post("/admin/credits/<int:source_id>/edit")
@admin_required
def edit_credit_source_route(source_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        existing = queries.get_credit_source(connection, source_id)
        if not existing:
            abort(404)
        try:
            values = _credit_source_form_values(existing)
            queries.update_credit_source(
                connection, source_id, values, session.get("user_id")
            )
        except ValueError as exc:
            connection.rollback()
            flash(str(exc), "error")
        else:
            security_audit.log_event(
                connection, "CREDIT_SOURCE_UPDATE", "credit_source", source_id,
                {"dataset": values["dataset"], "is_active": values["is_active"]},
            )
            connection.commit()
            flash("출처 항목을 수정했습니다.", "success")
    finally:
        connection.close()
    return redirect(url_for("credits_management_page"))


@app.post("/admin/credits/<int:source_id>/hide")
@admin_required
def hide_credit_source_route(source_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        source = queries.get_credit_source(connection, source_id)
        if not source:
            abort(404)
        queries.hide_credit_source(connection, source_id, session.get("user_id"))
        security_audit.log_event(
            connection, "CREDIT_SOURCE_HIDE", "credit_source", source_id,
            {"dataset": source["dataset"]},
        )
        connection.commit()
        flash("출처 항목을 공개 목록에서 숨겼습니다.", "success")
    finally:
        connection.close()
    return redirect(url_for("credits_management_page"))


@app.route("/credits")
def credits_page():
    connection = dashboard_db()
    try:
        credits_rows = _credits_rows(connection)
    finally:
        connection.close()
    return render_template(
        "credits.html",
        credits_rows=credits_rows,
        site_map_links=_site_map_links(),
    )


ERROR_PAGE_CONTENT = {
    400: ("요청을 처리할 수 없습니다", "입력값이 올바르지 않거나 요청이 만료되었습니다."),
    403: ("접근 권한이 없습니다", "현재 계정에는 이 페이지를 볼 수 있는 권한이 없습니다."),
    404: ("페이지를 찾을 수 없습니다", "주소가 변경되었거나 존재하지 않는 페이지입니다."),
    405: ("허용되지 않은 요청입니다", "이 주소에서는 해당 작업을 실행할 수 없습니다."),
    413: ("파일이 너무 큽니다", "허용된 업로드 용량을 초과했습니다."),
    500: ("일시적인 오류가 발생했습니다", "오류가 기록되었습니다. 잠시 후 다시 시도해주세요."),
}


def _render_error_page(status_code):
    title, message = ERROR_PAGE_CONTENT[status_code]
    locale = locale_from_environ(request.environ)
    title = translate_text(title, locale)
    message = translate_text(message, locale)
    if request.path.startswith("/api/") or request.is_json:
        return jsonify({"success": False, "message": message}), status_code
    return render_template(
        "error.html",
        status_code=status_code,
        error_title=title,
        error_message=message,
        site_map_links=_site_map_links(),
        seo_title=f"{status_code} | Casino IN",
        seo_description=message,
        seo_og_title=f"{status_code} | Casino IN",
        seo_og_description=message,
        seo_robots="noindex,nofollow",
    ), status_code


for _status_code in ERROR_PAGE_CONTENT:
    app.register_error_handler(
        _status_code,
        lambda error, code=_status_code: _render_error_page(code),
    )


def _percent_delta(today_value, prev_value):
    if prev_value in (None, 0):
        return None
    return round(((today_value - prev_value) / prev_value) * 100)


@app.route("/")
def public_home():
    today = today_kst_str()
    is_authenticated = bool(session.get("user_id"))
    connection = dashboard_db()
    try:
        important_news = news_reader.today_important_articles()
        official_documents = []
        official_overdue = []
        official_metrics = None
        official_db_updated_at = None
        action_items = []
        if is_authenticated:
            bug_report_owner = (
                None if session.get("role") == "admin"
                else (session.get("username") or "")
            )
            official_documents, _ = official_document_manager.list_documents(
                connection, per_page=100000
            )
            official_overdue = [
                item for item in official_documents
                if "접수 후 7일 경과" in item["review_reasons"]
            ]
            official_metrics = official_document_manager.dashboard_metrics(connection)
            official_update_status = official_document_manager.data_update_status(connection)
            official_db_updated_at = (
                official_document_manager.datetime_minute(
                    official_update_status["latest_updated_at"]
                )
                if official_update_status["latest_updated_at"]
                else None
            )
            action_items = queries.list_action_items(
                connection, reported_by=bug_report_owner
            )[:10]

        kpis = {
            "today_news": news_reader.count_today_articles(),
            "important_news": news_reader.count_today_important_articles(),
            "important_news_delta": _percent_delta(
                news_reader.count_today_important_articles(),
                news_reader.count_yesterday_important_articles(),
            ),
            "pending_action_items": (
                queries.count_action_items(connection, reported_by=bug_report_owner)
                if is_authenticated else 0
            ),
            "urgent_action_items": (
                queries.count_action_items(
                    connection, urgent_only=True, reported_by=bug_report_owner
                ) if is_authenticated else 0
            ),
            "new_competitor_issues": news_reader.count_new_issues_today_by_category(
                COMPETITOR_CATEGORY_KEYWORDS
            ),
            "new_policy_issues": news_reader.count_new_issues_today_by_category(
                POLICY_CATEGORY_KEYWORDS
            ),
            "ai_insights_count": queries.count_insights_for_date(connection, today),
        }

        recent_disclosures = queries.list_recent_disclosures(connection, days=7)[:10]
        news_updated_raw = news_reader.last_updated_at()
        market_quotes = _refresh_market_quotes_if_needed(connection)
        market_updated_at = max(
            (quote.get("fetched_at") or "" for quote in market_quotes),
            default=None,
        )
        economic_series = _refresh_economic_series_if_needed(connection)

        return render_template(
            "dashboard.html",
            kpis=kpis,
            important_news=important_news[:12],
            official_metrics=official_metrics,
            official_overdue=official_overdue[:10],
            official_recent=official_documents[:6],
            market_quotes=market_quotes,
            economic_series=economic_series,
            market_updated_at=(
                official_document_manager.datetime_minute(market_updated_at)
                if market_updated_at else None
            ),
            action_items=action_items,
            recent_disclosures=recent_disclosures,
            csrf_token=get_csrf_token(),
            is_authenticated=is_authenticated,
            casino_news_updated_at=(
                official_document_manager.datetime_minute(news_updated_raw)
                if news_updated_raw else None
            ),
            official_db_updated_at=official_db_updated_at,
        )
    finally:
        connection.close()


@app.route("/dashboard")
def dashboard_home():
    return redirect(_canonical_request_url("/"), code=301)


@app.route("/admin")
@admin_required
def paradian_portal_page():
    connection = dashboard_db()
    try:
        today = now_kst().date().isoformat()
        activity = queries.get_admin_dashboard_activity(connection, today)
        activity_max = max(
            (
                value
                for item in activity
                for value in (
                    item["new_members"], item["new_posts"], item["withdrawals"]
                )
            ),
            default=0,
        )
        for item in activity:
            item["label"] = item["day"][5:].replace("-", ".")
            for key in ("new_members", "new_posts", "withdrawals"):
                item[f"{key}_height"] = (
                    max(6, round(item[key] / activity_max * 100))
                    if item[key] and activity_max else 0
                )
        return render_template(
            "paradian_portal.html",
            admin_metrics=queries.get_admin_dashboard_metrics(connection, today),
            admin_activity=activity,
            activity_totals={
                key: sum(item[key] for item in activity)
                for key in ("new_members", "new_posts", "withdrawals")
            },
            metric_date=today,
        )
    finally:
        connection.close()


@app.route("/admin/portfolio")
@admin_required
def admin_portfolio_page():
    try:
        content = portfolio_content.snapshot()
        content_error = None
    except ValueError as exc:
        content = {"projects": [], "about": {}, "contact": {}, "logos": [], "skills": []}
        content_error = str(exc)
    connection = dashboard_db()
    try:
        tips = [dict(row) for row in connection.execute(
            """SELECT slug, title, category, draft, updated_at
               FROM tips_articles WHERE is_deleted=0
               ORDER BY updated_at DESC LIMIT 8"""
        ).fetchall()]
    finally:
        connection.close()
    return render_template(
        "admin_portfolio.html",
        files=portfolio_admin.list_files(),
        content=content,
        tips=tips,
        csrf_token=get_csrf_token(),
        success=request.args.get("success"),
        error=request.args.get("error") or content_error,
        active_section=request.args.get("section", "overview"),
    )


def _portfolio_redirect(section, *, success=None, error=None):
    values = {"section": section}
    if success:
        values["success"] = success
    if error:
        values["error"] = error
    return redirect(url_for("admin_portfolio_page", **values) + f"#{section}")


def _portfolio_log(event, target_type, target_id, metadata=None):
    connection = dashboard_db()
    try:
        security_audit.log_event(connection, event, target_type, target_id, metadata or {})
        connection.commit()
    finally:
        connection.close()


@app.post("/admin/portfolio/projects/save")
@admin_required
def admin_portfolio_save_project():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    try:
        record = portfolio_content.save_project(request.form)
    except ValueError as exc:
        return _portfolio_redirect("projects", error=str(exc))
    _portfolio_log("PORTFOLIO_PROJECT_SAVED", "portfolio_project", record["id"])
    return _portfolio_redirect("projects", success="프로젝트를 저장했습니다.")


@app.post("/admin/portfolio/projects/delete")
@admin_required
def admin_portfolio_delete_project():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    project_id = request.form.get("id", "")
    try:
        portfolio_content.delete_project(project_id)
    except (ValueError, FileNotFoundError):
        abort(404)
    _portfolio_log("PORTFOLIO_PROJECT_DELETED", "portfolio_project", project_id)
    return _portfolio_redirect("projects", success="프로젝트를 삭제했습니다.")


@app.post("/admin/portfolio/about/save")
@admin_required
def admin_portfolio_save_about():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    try:
        portfolio_content.save_about(request.form)
    except ValueError as exc:
        return _portfolio_redirect("about", error=str(exc))
    _portfolio_log("PORTFOLIO_ABOUT_SAVED", "portfolio_about", "profile")
    return _portfolio_redirect("about", success="소개 정보를 저장했습니다.")


@app.post("/admin/portfolio/about/photo")
@admin_required
def admin_portfolio_save_about_photo():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    upload = request.files.get("photo")
    if not upload or not upload.filename:
        return _portfolio_redirect("about", error="프로필 사진을 선택해주세요.")
    try:
        portfolio_content.save_about_photo(upload)
    except ValueError as exc:
        return _portfolio_redirect("about", error=str(exc))
    _portfolio_log("PORTFOLIO_PHOTO_SAVED", "portfolio_about", "photo")
    return _portfolio_redirect("about", success="포트폴리오 프로필 사진을 변경했습니다.")


@app.post("/admin/portfolio/contact/save")
@admin_required
def admin_portfolio_save_contact():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    try:
        portfolio_content.save_contact(request.form)
    except ValueError as exc:
        return _portfolio_redirect("contact", error=str(exc))
    _portfolio_log("PORTFOLIO_CONTACT_SAVED", "portfolio_contact", "contact")
    return _portfolio_redirect("contact", success="연락처를 저장했습니다.")


@app.post("/admin/portfolio/logos/save")
@admin_required
def admin_portfolio_save_logo():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    upload = request.files.get("image")
    if not upload or not upload.filename:
        return _portfolio_redirect("logos", error="로고 이미지를 선택해주세요.")
    try:
        record = portfolio_content.save_logo(request.form, upload)
    except ValueError as exc:
        return _portfolio_redirect("logos", error=str(exc))
    _portfolio_log("PORTFOLIO_LOGO_SAVED", "portfolio_logo", record["id"])
    return _portfolio_redirect("logos", success="로고를 추가했습니다.")


@app.post("/admin/portfolio/logos/delete")
@admin_required
def admin_portfolio_delete_logo():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    logo_id = request.form.get("id", "")
    try:
        portfolio_content.delete_logo(logo_id)
    except (ValueError, FileNotFoundError):
        abort(404)
    _portfolio_log("PORTFOLIO_LOGO_DELETED", "portfolio_logo", logo_id)
    return _portfolio_redirect("logos", success="로고를 삭제했습니다.")


@app.post("/admin/portfolio/skills/save")
@admin_required
def admin_portfolio_save_skill():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    try:
        record = portfolio_content.save_skill(request.form, request.files.get("icon"))
    except ValueError as exc:
        return _portfolio_redirect("skills", error=str(exc))
    _portfolio_log("PORTFOLIO_SKILL_SAVED", "portfolio_skill", record["id"])
    return _portfolio_redirect("skills", success="기술 정보를 저장했습니다.")


@app.post("/admin/portfolio/skills/delete")
@admin_required
def admin_portfolio_delete_skill():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    skill_id = request.form.get("id", "")
    try:
        portfolio_content.delete_skill(skill_id)
    except (ValueError, FileNotFoundError):
        abort(404)
    _portfolio_log("PORTFOLIO_SKILL_DELETED", "portfolio_skill", skill_id)
    return _portfolio_redirect("skills", success="기술 정보를 삭제했습니다.")


@app.post("/admin/portfolio/files")
@admin_required
def admin_portfolio_upload_file():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return _portfolio_redirect("files", error="업로드할 파일을 선택해주세요.")
    try:
        record = portfolio_admin.save_upload(upload)
    except ValueError as error:
        return _portfolio_redirect("files", error=str(error))
    connection = dashboard_db()
    try:
        security_audit.log_event(
            connection, "PORTFOLIO_FILE_UPLOADED", "portfolio_file", record["name"],
            {"size": record["size"], "url": record["url"]},
        )
        connection.commit()
    finally:
        connection.close()
    return _portfolio_redirect("files", success=f"{record['name']} 업로드가 완료되었습니다.")


@app.post("/admin/portfolio/files/delete")
@admin_required
def admin_portfolio_delete_file():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    filename = request.form.get("filename", "")
    try:
        portfolio_admin.delete_file(filename)
    except (ValueError, FileNotFoundError):
        abort(404)
    connection = dashboard_db()
    try:
        security_audit.log_event(
            connection, "PORTFOLIO_FILE_DELETED", "portfolio_file", filename,
        )
        connection.commit()
    finally:
        connection.close()
    return _portfolio_redirect("files", success=f"{filename} 파일을 삭제했습니다.")


@app.post("/admin/portfolio/files/bulk-delete")
@admin_required
def admin_portfolio_bulk_delete_files():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    try:
        filenames = portfolio_admin.delete_files(request.form.getlist("filenames"))
    except ValueError as exc:
        return _portfolio_redirect("files", error=str(exc))
    except FileNotFoundError:
        abort(404)
    for filename in filenames:
        _portfolio_log("PORTFOLIO_FILE_DELETED", "portfolio_file", filename, {"bulk": True})
    return _portfolio_redirect("files", success=f"외부 링크 파일 {len(filenames)}개를 삭제했습니다.")


# ============================================================
# Action Items
# ============================================================

def can_access_bug_report(item):
    return bool(
        item
        and item.get("source_type") in (None, "bug_report")
        and (
            session.get("role") == "admin"
            or (
                session.get("username")
                and item.get("reported_by") == session.get("username")
            )
        )
    )


# Backward-compatible public name used by the current tests and newer callers.
can_access_action_item = can_access_bug_report


def _visible_action_items(connection, status=None):
    username = session.get("username") or ""
    if not username:
        return []
    return queries.list_action_items(
        connection,
        status=status,
        reported_by=None if session.get("role") == "admin" else username,
        source_type="bug_report",
    )


@app.get("/board/bug-reports")
def action_items_page():
    connection = dashboard_db()
    try:
        if not membership.can_board(
            connection, "bug_reports", "read",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        status_filter = request.args.get("status") or None
        return render_template(
            "action_items.html",
            items=_visible_action_items(connection, status_filter),
            csrf_token=get_csrf_token(),
            status_filter=status_filter,
            is_admin=session.get("role") == "admin",
            can_write=membership.can_board(
                connection, "bug_reports", "write",
                session.get("user_id"), session.get("role"),
            ),
        )
    finally:
        connection.close()


@app.post("/board/bug-reports")
@login_required
def create_action_item_route():
    connection = dashboard_db()
    try:
        if not membership.can_board(
            connection, "bug_reports", "write",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        is_admin = session.get("role") == "admin"
        can_write = True
        if not validate_csrf(request.form.get("csrf_token", "")):
            return render_template(
                "action_items.html",
                error="요청이 만료되었습니다. 다시 시도해주세요.",
                items=_visible_action_items(connection),
                csrf_token=get_csrf_token(),
                is_admin=is_admin,
                can_write=can_write,
            ), 400

        title = (request.form.get("title") or "").strip()
        if not title or len(title) > 150:
            return render_template(
                "action_items.html",
                error="제목은 1~150자로 입력해주세요.",
                items=_visible_action_items(connection),
                csrf_token=get_csrf_token(),
                is_admin=is_admin,
                can_write=can_write,
            ), 400

        description = (request.form.get("description") or "").strip()
        bug_page = (request.form.get("bug_page") or "").strip()
        environment = (request.form.get("environment") or "").strip()
        if len(bug_page) > 200 or len(environment) > 200:
            return render_template(
                "action_items.html",
                error="관련 화면과 사용 환경은 각각 200자 이내로 입력해주세요.",
                items=_visible_action_items(connection),
                csrf_token=get_csrf_token(),
                is_admin=is_admin,
                can_write=can_write,
            ), 400
        if not description or len(description) > 5000:
            return render_template(
                "action_items.html",
                error="내용은 1~5,000자로 입력해주세요.",
                items=_visible_action_items(connection),
                csrf_token=get_csrf_token(),
                is_admin=is_admin,
                can_write=can_write,
            ), 400
        priority = request.form.get("priority") or "보통"
        if priority not in {"긴급", "높음", "보통", "낮음"}:
            priority = "보통"
        feedback_type = request.form.get("feedback_type") or "일반 의견"
        if feedback_type not in {"질문", "버그 제보", "기능 제안", "일반 의견"}:
            feedback_type = "일반 의견"
        reporter = session.get("username") or ""
        current = now_kst()
        recent_since = (current - timedelta(minutes=10)).isoformat()
        daily_since = (current - timedelta(days=1)).isoformat()
        recent_count = connection.execute(
            """
            SELECT COUNT(*) FROM action_items
            WHERE source_type='bug_report' AND reported_by=? AND created_at>=?
            """,
            (reporter, recent_since),
        ).fetchone()[0]
        daily_count = connection.execute(
            """
            SELECT COUNT(*) FROM action_items
            WHERE source_type='bug_report' AND reported_by=? AND created_at>=?
            """,
            (reporter, daily_since),
        ).fetchone()[0]
        if recent_count >= 5 or daily_count >= 30:
            return render_template(
                "action_items.html",
                error="글 작성 횟수가 너무 많습니다. 잠시 후 다시 시도해주세요.",
                items=_visible_action_items(connection),
                csrf_token=get_csrf_token(),
                is_admin=is_admin,
                can_write=can_write,
            ), 429
        item_id = queries.create_action_item(
            connection,
            title=title,
            description=description,
            owner=(
                (request.form.get("owner") or "").strip()[:80] or None
                if is_admin else None
            ),
            priority=priority,
            source_type="bug_report",
            status="접수",
            reported_by=reporter,
            bug_page=bug_page,
            environment=environment,
            feedback_type=feedback_type,
        )
        bug_url = url_for("action_item_detail", item_id=item_id, _external=True)
        alert_lines = [
            "💬 <b>새 버그 및 건의</b>",
            "",
            f"<b>제목:</b> {escape_html(title)}",
            f"<b>유형:</b> {escape_html(feedback_type)}",
            f"<b>심각도:</b> {escape_html(priority)}",
            f"<b>제보자:</b> {escape_html(reporter or '-')}",
            f"<b>발생 화면:</b> {escape_html(bug_page or '-')}",
            f"<b>사용 환경:</b> {escape_html(environment or '-')}",
            "",
            escape_html(description[:800] or "상세 내용 없음"),
            "",
            f'<a href="{bug_url}">게시글 열기</a> · #{item_id}',
        ]
        if not telegram_alert.send_alert("\n".join(alert_lines), force=True):
            queries.log_error(
                connection,
                "bug_report_alert",
                "telegram_send_failed",
                f"버그 및 건의 #{item_id} Telegram 알림 전송 실패",
            )
        return redirect(url_for("action_items_page"))
    finally:
        connection.close()


@app.get("/admin/action-items")
@admin_required
def admin_action_items_page():
    """Preserve the existing operational action-item manager for admins."""

    connection = dashboard_db()
    try:
        return render_template(
            "admin_action_items.html",
            items=queries.list_action_items(
                connection, exclude_source_type="bug_report"
            ),
            csrf_token=get_csrf_token(),
        )
    finally:
        connection.close()


@app.post("/admin/action-items")
@admin_required
def create_admin_action_item_route():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    title = (request.form.get("title") or "").strip()
    description = (request.form.get("description") or "").strip()
    owner = (request.form.get("owner") or "").strip()
    due_date = (request.form.get("due_date") or "").strip() or None
    due_date_confidence = request.form.get("due_date_confidence") or "unclear"
    priority = request.form.get("priority") or "보통"
    if not title or len(title) > 150:
        abort(400)
    if len(description) > 5000 or len(owner) > 80:
        abort(400)
    if due_date:
        try:
            datetime.strptime(due_date, "%Y-%m-%d")
        except ValueError:
            abort(400)
    if due_date_confidence not in {"confirmed", "estimated", "unclear"}:
        due_date_confidence = "unclear"
    if priority not in {"긴급", "높음", "보통", "낮음"}:
        priority = "보통"
    connection = dashboard_db()
    try:
        queries.create_action_item(
            connection,
            title=title,
            description=description,
            owner=owner or None,
            due_date=due_date,
            due_date_confidence=due_date_confidence,
            priority=priority,
            source_type="manual",
            status="미착수",
        )
    finally:
        connection.close()
    return redirect(url_for("admin_action_items_page"))


@app.get("/board/bug-reports/<int:item_id>")
@login_required
def action_item_detail(item_id):
    connection = dashboard_db()
    try:
        item = queries.get_action_item(connection, item_id)
        if not item:
            abort(404)
        if not membership.can_board(
            connection, "bug_reports", "read",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        if not can_access_bug_report(item):
            abort(403)
        queries.record_unique_action_item_view(
            connection, item_id, _community_viewer_hash()
        )
        item = queries.get_action_item(connection, item_id)
        comments = queries.list_action_item_comments(connection, item_id)
        return render_template(
            "action_item_detail.html",
            item=item,
            description_html=_render_community_markdown(item.get("description")),
            comments=comments,
            csrf_token=get_csrf_token(),
            is_admin=session.get("role") == "admin",
            can_comment=membership.can_board(
                connection, "bug_reports", "comment",
                session.get("user_id"), session.get("role"),
            ),
        )
    finally:
        connection.close()


@app.post("/board/bug-reports/<int:item_id>/comments")
@login_required
def add_action_item_comment(item_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        item = queries.get_action_item(connection, item_id)
        if not item:
            abort(404)
        if not membership.can_board(
            connection, "bug_reports", "comment",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        if not can_access_bug_report(item):
            abort(403)
        try:
            queries.create_action_item_comment(
                connection,
                item_id,
                session["user_id"],
                request.form.get("content", ""),
            )
            flash("댓글을 등록했습니다.", "success")
        except ValueError as error:
            flash(str(error), "error")
    finally:
        connection.close()
    return redirect(url_for("action_item_detail", item_id=item_id) + "#comments")


@app.post("/board/bug-reports/<int:item_id>/comments/<int:comment_id>/edit")
@login_required
def edit_action_item_comment(item_id, comment_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        item = queries.get_action_item(connection, item_id)
        comment = queries.get_action_item_comment(connection, comment_id)
        if not item or not comment or comment["action_item_id"] != item_id or comment["is_deleted"]:
            abort(404)
        if not membership.can_board(
            connection, "bug_reports", "comment",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        if not can_access_bug_report(item):
            abort(403)
        if comment["author_id"] != session.get("user_id") and session.get("role") != "admin":
            abort(403)
        try:
            queries.update_action_item_comment(
                connection, comment_id, request.form.get("content", "")
            )
            flash("댓글을 수정했습니다.", "success")
        except ValueError as error:
            flash(str(error), "error")
    finally:
        connection.close()
    return redirect(url_for("action_item_detail", item_id=item_id) + "#comments")


@app.post("/board/bug-reports/<int:item_id>/comments/<int:comment_id>/delete")
@login_required
def delete_action_item_comment(item_id, comment_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        item = queries.get_action_item(connection, item_id)
        comment = queries.get_action_item_comment(connection, comment_id)
        if not item or not comment or comment["action_item_id"] != item_id or comment["is_deleted"]:
            abort(404)
        if not membership.can_board(
            connection, "bug_reports", "comment",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        if not can_access_bug_report(item):
            abort(403)
        if comment["author_id"] != session.get("user_id") and session.get("role") != "admin":
            abort(403)
        queries.delete_action_item_comment(connection, comment_id, session["user_id"])
        flash("댓글을 삭제했습니다.", "success")
    finally:
        connection.close()
    return redirect(url_for("action_item_detail", item_id=item_id) + "#comments")


@app.route("/board/bug-reports/<int:item_id>/update", methods=["POST"])
@login_required
def update_action_item_route(item_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        return redirect(url_for("action_items_page"))

    connection = dashboard_db()
    try:
        item = queries.get_action_item(connection, item_id)
        if not item:
            abort(404)
        if not membership.can_board(
            connection, "bug_reports", "write",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        is_admin = session.get("role") == "admin"
        if not is_admin and not can_access_bug_report(item):
            abort(403)

        fields = {}
        allowed_fields = (
            ("status", "priority", "owner", "memo", "title", "description",
             "bug_page", "environment", "feedback_type")
            if is_admin
            else ("priority", "title", "description", "bug_page", "environment", "feedback_type")
        )
        for key in allowed_fields:
            if key in request.form:
                fields[key] = (request.form.get(key) or "").strip()
        if fields.get("feedback_type") not in {
            None, "질문", "버그 제보", "기능 제안", "일반 의견"
        }:
            abort(400)
        if "title" in fields and (
            not fields["title"] or len(fields["title"]) > 150
        ):
            abort(400)
        if "description" in fields and (
            not fields["description"] or len(fields["description"]) > 5000
        ):
            abort(400)
        if len(fields.get("bug_page", "")) > 200:
            abort(400)
        if len(fields.get("environment", "")) > 200:
            abort(400)
        if fields.get("priority") not in {None, "긴급", "높음", "보통", "낮음"}:
            abort(400)
        if len(fields.get("owner", "")) > 80 or len(fields.get("memo", "")) > 5000:
            abort(400)
        if fields:
            queries.update_action_item(connection, item_id, **fields)
        if is_admin and request.form.get("approve") == "1":
            queries.approve_action_item(connection, item_id)
    finally:
        connection.close()
    next_url = request.form.get("next", "")
    if next_url.startswith("/board/bug-reports/"):
        return redirect(next_url)
    if next_url == url_for("admin_action_items_page"):
        return redirect(next_url)
    return redirect(url_for("action_items_page"))


@app.route("/board/bug-reports/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_action_item_route(item_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        return redirect(url_for("action_items_page"))
    connection = dashboard_db()
    try:
        item = queries.get_action_item(connection, item_id)
        if not item:
            abort(404)
        if not membership.can_board(
            connection, "bug_reports", "write",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        if session.get("role") != "admin":
            abort(403)
        queries.delete_action_item(connection, item_id)
    finally:
        connection.close()
    next_url = request.form.get("next", "")
    if next_url == url_for("admin_action_items_page"):
        return redirect(next_url)
    return redirect(url_for("action_items_page"))


# ============================================================
# 실적
# ============================================================

def valid_performance_ingest_signature(raw_body, timestamp, signature):
    """Brity 자동화가 공유 봇 토큰으로 서명한 요청인지 검증한다."""
    if not config.TELEGRAM_BOT_TOKEN or not timestamp or not signature:
        return False
    try:
        request_time = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(int(time.time()) - request_time) > 300:
        return False
    message = timestamp.encode("ascii") + b"." + raw_body
    expected = hmac.new(
        config.TELEGRAM_BOT_TOKEN.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.post("/api/performance-ingest")
def performance_ingest_api():
    raw_body = request.get_data(cache=True)
    if not valid_performance_ingest_signature(
        raw_body,
        request.headers.get("X-Performance-Timestamp", ""),
        request.headers.get("X-Performance-Signature", ""),
    ):
        return jsonify({"success": False, "message": "인증에 실패했습니다."}), 401
    data = request.get_json(silent=True) or {}
    raw_text = str(data.get("raw_text") or "").strip()
    header_type = performance_parser.detect_header_type(raw_text)
    if not raw_text or len(raw_text) > 10000 or header_type is None:
        return jsonify({"success": False, "message": "실적 메시지 형식이 아닙니다."}), 400
    received_at = str(data.get("received_at") or "").strip()
    try:
        received = datetime.fromisoformat(received_at)
    except ValueError:
        return jsonify({"success": False, "message": "수집 시간이 올바르지 않습니다."}), 400
    parsed, parse_error = performance_parser.parse(raw_text)
    connection = dashboard_db()
    try:
        queries.save_performance_report(
            connection,
            report_date=received.strftime("%Y-%m-%d"),
            telegram_update_id=None,
            telegram_message_id=str(data.get("event_id") or "")[:120],
            telegram_chat_id="direct:BrityBoardWatch",
            message_kind=str(data.get("message_kind") or "text")[:20],
            header_type=header_type,
            raw_text=raw_text,
            parsed_data=(parsed.fields if parsed else None),
            parsing_status=("ok" if parsed else "failed"),
            parsing_error=parse_error,
            received_at=received.isoformat(),
        )
    finally:
        connection.close()
    return jsonify({"success": True, "parsing_status": "ok" if parsed else "failed"})


@app.route("/admin/performance")
@login_required
def performance_page():
    connection = dashboard_db()
    try:
        report_date = request.args.get("date") or today_kst_str()
        reports = queries.list_performance_reports(connection, report_date)
        casino_trend = queries.get_casino_sales_trend(connection, report_date, days=30)
        return render_template(
            "performance.html",
            reports=reports,
            report_date=report_date,
            casino_trend=casino_trend,
        )
    finally:
        connection.close()


@app.route("/resources/source-data")
@login_required
def source_download_page():
    """로그인 사용자용 통합 숫자 데이터 조회·복사 화면."""
    connection = dashboard_db()
    try:
        if not membership.can_board(
            connection, "source_data", "read",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        source_data_repository.synchronize_existing_data(connection)
        include_internal = session.get("role") == "admin"
        view = source_data_repository.build_view(
            connection,
            grain=request.args.get("grain", "monthly"),
            start_date=request.args.get("start_date"),
            end_date=request.args.get("end_date"),
            selected_keys=request.args.getlist("series"),
            include_internal=include_internal,
        )
        return render_template(
            "source_download.html",
            source_view=view,
            include_internal=include_internal,
        )
    finally:
        connection.close()


@app.route("/market/tourism")
def tourism_trend_page():
    connection = dashboard_db()
    try:
        comparison = queries.get_tourism_ytd_comparison(connection)
        freshness = queries.get_data_freshness(
            connection, "tourism_visitor_stats", "tourism_stats_sync"
        )
        return render_template(
            "tourism_trend.html",
            tourism_comparison=comparison,
            tourism_checked_at=freshness["checked_at"],
            tourism_changed_at=freshness["changed_at"],
            tourism_check_status=freshness["check_status"],
        )
    finally:
        connection.close()


@app.route("/market/casino-industry")
def casino_industry_page():
    return render_template(
        "casino_industry.html",
        casino_industry=casino_industry.build_dashboard(
            request.args.get("region", "").strip()
        ),
    )


@app.route("/market/casino-industry/insights")
def casino_insights_page():
    connection = dashboard_db()
    try:
        return render_template(
            "casino_insights.html",
            insights=casino_insights.build_dashboard(
                connection, request.args.get("month", "").strip()
            ),
        )
    finally:
        connection.close()


@app.route("/market/casino-industry/market-share")
def casino_market_share_page():
    connection = dashboard_db()
    try:
        return render_template(
            "casino_market_share.html",
            market_share=casino_market_share.build_dashboard(
                connection,
                request.args.get("year"),
                request.args.get("exclude_kangwon") == "1",
            ),
        )
    finally:
        connection.close()


@app.route("/market/casino-industry/visitors")
def casino_visitors_page():
    return render_template(
        "casino_history.html",
        mode="visitors",
        page_title="연도별 카지노 이용객",
        page_description="외래 방한객과 외국인전용 카지노 이용객의 장기 추이·점유율·증감률을 확인합니다.",
        statistics=casino_statistics.build_visitors(),
    )


@app.route("/market/casino-industry/revenue")
def casino_revenue_page():
    return render_template(
        "casino_history.html",
        mode="revenue",
        page_title="연도별 카지노 매출액 비율",
        page_description="관광 외화수입 대비 카지노 외화수입의 장기 추이와 점유율을 확인합니다.",
        statistics=casino_statistics.build_revenue(),
    )


@app.route("/market/casino-industry/fund")
def casino_fund_page():
    return render_template(
        "casino_fund.html",
        fund=casino_statistics.build_fund(),
    )


@app.route("/market/stocks")
def market_trend_page():
    connection = dashboard_db()
    try:
        quotes = _refresh_market_quotes_if_needed(connection)
        domestic_quotes = [
            quote for quote in quotes if quote.get("asset_type") != "global_stock"
        ]
        global_quotes = [
            quote for quote in quotes if quote.get("asset_type") == "global_stock"
        ]
        freshness = _market_freshness(quotes)
        latest_run = queries.get_latest_completed_run(connection, "market_quote_sync")
        return render_template(
            "market_trend.html",
            market_quotes=domestic_quotes,
            global_market_quotes=global_quotes,
            market_domestic_checked_at=freshness["domestic_checked_at"],
            market_global_checked_at=freshness["global_checked_at"],
            market_domestic_base_date=freshness["domestic_base_date"],
            market_global_base_date=freshness["global_base_date"],
            market_check_status=latest_run.get("status") if latest_run else None,
        )
    finally:
        connection.close()


@app.route("/news")
def related_news_page():
    allowed_days = {7, 30, 90, 365}
    try:
        days = int(request.args.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    if days not in allowed_days:
        days = 30

    term = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    impact = request.args.get("impact", "").strip()
    important_only = request.args.get("importance") == "important"
    include_entertainment = request.args.get("include_entertainment") == "1"
    page = max(1, request.args.get("page", 1, type=int))
    page_size = 10
    total_articles = news_reader.count_filtered_articles(
        days=days, term=term, category=category, impact_direction=impact,
        important_only=important_only, include_entertainment=include_entertainment,
    )
    page_count = max(1, (total_articles + page_size - 1) // page_size)
    page = min(page, page_count)
    articles = news_reader.list_articles(
        days=days,
        term=term,
        category=category,
        impact_direction=impact,
        important_only=important_only,
        include_entertainment=include_entertainment,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    connection = dashboard_db()
    try:
        if g.locale == "en":
            articles = content_translation.apply_cached(
                connection, "news", articles, id_field="article_id"
            )
        # Executive insights combine internal performance, official documents,
        # and research uploads. They must never be exposed to public or regular
        # user sessions through the otherwise-public news page.
        show_executive_insights = session.get("role") == "admin"
        executive_insights = (
            queries.list_recent_executive_insights(connection, days=days, limit=10)
            if show_executive_insights
            else []
        )
    finally:
        connection.close()
    return render_template(
        "related_news.html",
        articles=articles,
        categories=news_reader.list_categories(),
        news_stats=news_reader.article_stats(days),
        executive_insights=executive_insights,
        show_executive_insights=show_executive_insights,
        news_updated_at=news_reader.last_updated_at(),
        selected_days=days,
        selected_term=term,
        selected_category=category,
        selected_impact=impact,
        important_only=important_only,
        include_entertainment=include_entertainment,
        news_page=page,
        news_page_count=page_count,
        news_total_count=total_articles,
    )


@app.route("/news/overseas")
def overseas_news_page():
    allowed_days = {7, 14, 30, 90, 365}
    days = request.args.get("days", 30, type=int)
    if days not in allowed_days:
        days = 30
    region = request.args.get("region", "").strip().lower()
    if region not in {"", "macau", "japan"}:
        region = ""
    term = request.args.get("q", "").strip()[:100]
    category = request.args.get("category", "").strip()[:50]
    impact = request.args.get("impact", "").strip().lower()
    if impact not in {"", "positive", "negative", "neutral", "mixed"}:
        impact = ""
    important_only = request.args.get("importance") == "important"
    page = max(1, request.args.get("page", 1, type=int))
    page_size = 10

    connection = dashboard_db()
    try:
        total_articles = overseas_news.count_articles(
            connection, days=days, region=region, term=term, category=category,
            impact=impact, important_only=important_only,
        )
        page_count = max(1, (total_articles + page_size - 1) // page_size)
        page = min(page, page_count)
        articles = overseas_news.list_articles(
            connection,
            days=days,
            region=region,
            term=term,
            category=category,
            impact=impact,
            important_only=important_only,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        news_stats = overseas_news.stats(connection, days=days)
        categories = overseas_news.list_categories(connection)
        sync_state = overseas_news.sync_state(connection)
    finally:
        connection.close()

    return render_template(
        "overseas_news.html",
        articles=articles,
        news_stats=news_stats,
        categories=categories,
        sync_state=sync_state,
        selected_days=days,
        selected_region=region,
        selected_term=term,
        selected_category=category,
        selected_impact=impact,
        important_only=important_only,
        news_page=page,
        news_page_count=page_count,
        news_total_count=total_articles,
    )


@app.route("/news/overseas/<int:article_id>/analyze", methods=["POST"])
@admin_required
def analyze_overseas_news_article(article_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        article = connection.execute(
            "SELECT id, original_title FROM overseas_news_articles WHERE id=?",
            (article_id,),
        ).fetchone()
        if not article:
            abort(404)
        result, error = overseas_news.analyze_article(
            connection, article_id, bypass_daily_limits=True
        )
        security_audit.log_event(
            connection,
            "OVERSEAS_NEWS_AI_ANALYSIS",
            "overseas_news_article",
            article_id,
            {
                "title": article["original_title"],
                "result": "completed" if result else "failed",
                "warning": error,
            },
            success=bool(result),
        )
        connection.commit()
        if result and error:
            flash("AI 분석은 완료했지만 중요 뉴스 웹 검증은 완료하지 못했습니다.", "warning")
        elif result:
            flash("해외뉴스 AI 분석이 완료되었습니다.", "success")
        else:
            flash(f"해외뉴스 AI 분석에 실패했습니다: {error}", "error")
        return redirect(url_for("overseas_news_page", _anchor=f"overseas-news-{article_id}"))
    finally:
        connection.close()


@app.route("/market/exchange-rates-and-oil")
def economic_trend_page():
    connection = dashboard_db()
    try:
        series = _refresh_economic_series_if_needed(connection)
        oil_series = [item for item in series if item["category"] == "oil"]
        exchange_series = [item for item in series if item["category"] == "exchange"]
        freshness = _economic_freshness(series)
        latest_run = queries.get_latest_completed_run(connection, "economic_data_sync")
        return render_template(
            "economic_trend.html",
            oil_series=oil_series,
            exchange_series=exchange_series,
            oil_checked_at=freshness["oil_checked_at"],
            oil_changed_at=freshness["oil_changed_at"],
            exchange_checked_at=freshness["exchange_checked_at"],
            exchange_changed_at=freshness["exchange_changed_at"],
            economic_check_status=latest_run.get("status") if latest_run else None,
        )
    finally:
        connection.close()


@app.route("/market/holidays")
def holiday_calendar_page():
    from services import holiday_calendar
    return render_template(
        "holiday_calendar.html",
        holiday_calendar=holiday_calendar.build_calendar(
            request.args.get("year", 2026, type=int),
            request.args.get("country", ""),
        ),
    )


@app.route("/companies/salary-ratings")
def salary_trend_page():
    from services import casino_industry

    connection = dashboard_db()
    try:
        items = queries.list_salary_dashboard(connection)
        items = salary_data.merge_operator_cards(
            items, casino_industry.list_operator_companies()
        )
        latest_run = queries.get_latest_completed_run(connection, "salary_sync")
        return render_template(
            "salary_trend.html",
            salary_items=items,
            salary_checked_at=latest_run.get("finished_at") if latest_run else None,
            salary_check_status=latest_run.get("status") if latest_run else None,
        )
    finally:
        connection.close()


@app.route("/companies/recruitment")
def recruitment_page():
    term = request.args.get("q", "").strip()
    source = request.args.get("source", "").strip()
    employment_type = request.args.get("employment_type", "").strip()
    connection = dashboard_db()
    try:
        jobs = queries.list_recruitment_jobs(
            connection, term=term, source=source, employment_type=employment_type
        )
        latest_run = queries.get_latest_completed_run(connection, "recruitment_sync")
        return render_template(
            "recruitment.html", jobs=jobs, term=term, selected_source=source,
            selected_employment_type=employment_type,
            recruitment_checked_at=latest_run.get("finished_at") if latest_run else None,
            recruitment_check_status=latest_run.get("status") if latest_run else None,
        )
    finally:
        connection.close()


# ============================================================
# 공시·재무
# ============================================================

def _disclosures_context(connection, error=None):
    try:
        days = max(1, min(int(request.args.get("days", 90)), 1095))
    except (TypeError, ValueError):
        days = 90
    companies = queries.list_monitored_companies(connection)
    selected_company = (request.args.get("company") or "").strip()
    selected = next(
        (item for item in companies if item["name"] == selected_company), None
    )
    if selected_company and not selected:
        selected_company = ""
    disclosures = queries.list_recent_disclosures(
        connection,
        days=days,
        company_name=selected_company or None,
        dart_corp_code=selected.get("dart_corp_code") if selected else None,
    )
    freshness = queries.get_data_freshness(
        connection, "dart_disclosures", "dart_sync", "fetched_at"
    )
    ir_documents = queries.list_research_documents(
        connection,
        company_name=selected_company or None,
        document_type="ir",
    )
    cutoff_date = (now_kst() - timedelta(days=days)).date()

    def ir_document_is_within_period(item):
        raw_date = str(
            item.get("report_date") or item.get("created_at") or ""
        )[:10]
        try:
            return datetime.fromisoformat(raw_date).date() >= cutoff_date
        except ValueError:
            # 날짜가 없는 기존 자료를 필터 때문에 숨기지 않는다.
            return True

    ir_documents = [
        item
        for item in ir_documents
        if ir_document_is_within_period(item)
    ]
    company_filings = [
        {
            "source_type": "dart",
            "sort_date": str(item.get("rcept_dt") or "").replace("-", "")[:8],
            "disclosure": item,
            "ir_document": None,
        }
        for item in disclosures
    ]
    company_filings.extend(
        {
            "source_type": "ir",
            "sort_date": str(
                item.get("report_date") or item.get("created_at") or ""
            ).replace("-", "")[:8],
            "disclosure": None,
            "ir_document": item,
        }
        for item in ir_documents
    )
    company_filings.sort(
        key=lambda item: (item["sort_date"], item["source_type"] == "ir"),
        reverse=True,
    )
    page_size = 20
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    filing_total = len(company_filings)
    filing_pages = max(1, (filing_total + page_size - 1) // page_size)
    page = min(page, filing_pages)
    start = (page - 1) * page_size
    company_filings = company_filings[start:start + page_size]
    page_disclosures = [
        item["disclosure"] for item in company_filings
        if item["source_type"] == "dart"
    ]
    analyses = queries.list_latest_disclosure_analyses(
        connection, (item["id"] for item in page_disclosures)
    )
    return {
        "disclosures": disclosures,
        "analyses": analyses,
        "ir_documents": ir_documents,
        "company_filings": company_filings,
        "filing_total": filing_total,
        "filing_page": page,
        "filing_pages": filing_pages,
        "companies": companies,
        "selected_company": selected_company,
        "days": days,
        "csrf_token": get_csrf_token(),
        "error": error,
        "notice": (request.args.get("notice") or "").strip(),
        "disclosure_checked_at": official_document_manager.datetime_minute(
            freshness["checked_at"]
        ) if freshness["checked_at"] else None,
        "disclosure_changed_at": official_document_manager.datetime_minute(
            freshness["changed_at"]
        ) if freshness["changed_at"] else None,
        "disclosure_check_status": freshness["check_status"],
    }


@app.route("/companies/disclosures")
def disclosures_page():
    connection = dashboard_db()
    try:
        return render_template("disclosures.html", **_disclosures_context(connection))
    finally:
        connection.close()


@app.route("/companies/disclosures/ir", methods=["POST"])
@login_required
def upload_ir_document():
    if session.get("role") != "admin":
        abort(403)
    connection = dashboard_db()
    saved_file = None
    document_id = None
    try:
        if not validate_csrf(request.form.get("csrf_token", "")):
            return render_template(
                "disclosures.html",
                **_disclosures_context(connection, "요청이 만료되었습니다. 다시 시도해주세요."),
            ), 400
        allowed_companies = {
            item["name"] for item in queries.list_monitored_companies(connection)
        }
        company_name = (request.form.get("company_name") or "").strip()
        if company_name not in allowed_companies:
            return render_template(
                "disclosures.html",
                **_disclosures_context(connection, "분석 대상 회사를 선택해주세요."),
            ), 400
        uploaded = request.files.get("document")
        if not uploaded or not uploaded.filename:
            return render_template(
                "disclosures.html",
                **_disclosures_context(connection, "업로드할 PDF를 선택해주세요."),
            ), 400
        extracted = document_library.save_and_extract(uploaded)
        saved_file = extracted["stored_filename"]
        duplicate = queries.find_research_document_by_hash(
            connection, company_name, extracted["sha256"]
        )
        if duplicate:
            document_library.remove_file(saved_file)
            saved_file = None
            return render_template(
                "disclosures.html",
                **_disclosures_context(
                    connection,
                    f"같은 파일이 이미 등록되어 있습니다: {duplicate['title']}",
                ),
            ), 409
        submitted_title = (request.form.get("title") or "").strip()[:200]
        document_id = queries.create_research_document(
            connection,
            document_type="ir",
            company_name=company_name,
            company_names=[company_name],
            title=submitted_title or extracted["original_filename"].rsplit(".", 1)[0],
            publisher=(request.form.get("publisher") or "").strip()[:120] or None,
            report_date=(request.form.get("report_date") or "").strip()[:10] or None,
            original_filename=extracted["original_filename"],
            stored_filename=extracted["stored_filename"],
            mime_type=extracted["mime_type"],
            file_size=extracted["file_size"],
            sha256=extracted["sha256"],
            page_count=extracted["page_count"],
            extracted_text=extracted["extracted_text"],
            extraction_status=extracted["extraction_status"],
            uploaded_by=session.get("username"),
        )
        saved_file = None
        document = queries.get_research_document(
            connection, document_id, document_type="ir"
        )
        analysis, analysis_error = ai_insights.analyze_research_document(
            connection, document
        )
        queries.update_research_document_analysis(
            connection,
            document_id,
            analysis=analysis,
            error_message=analysis_error,
            document_type="ir",
        )
        suggested_title = str((analysis or {}).get("suggested_title") or "").strip()[:200]
        if not submitted_title and suggested_title:
            queries.update_research_document_title(
                connection, document_id, suggested_title, document_type="ir"
            )
        security_audit.log_event(
            connection,
            "PDF_UPLOAD",
            "ir_document",
            document_id,
            {
                "company_name": company_name,
                "filename": extracted["original_filename"],
                "file_size": extracted["file_size"],
                "sha256": extracted["sha256"],
                "page_count": extracted["page_count"],
            },
        )
        connection.commit()
        notice = "IR 업로드 및 AI 분석이 완료되었습니다." if analysis else (
            "IR 자료는 저장했지만 AI 분석은 완료되지 않았습니다."
        )
        return redirect(url_for("disclosures_page", notice=notice))
    except document_library.DocumentUploadError as error:
        if saved_file:
            document_library.remove_file(saved_file)
        return render_template(
            "disclosures.html", **_disclosures_context(connection, str(error))
        ), 400
    except Exception:
        if document_id:
            document = queries.get_research_document(
                connection, document_id, document_type="ir"
            )
            if document:
                queries.delete_research_document(
                    connection, document_id, document_type="ir"
                )
                try:
                    document_library.remove_file(document["stored_filename"])
                except OSError:
                    logger.exception("실패한 IR 업로드 파일 정리 실패: %s", document_id)
        elif saved_file:
            document_library.remove_file(saved_file)
        logger.exception("IR 업로드 처리 실패")
        return render_template(
            "disclosures.html",
            **_disclosures_context(connection, "IR 자료 처리 중 오류가 발생했습니다."),
        ), 500
    finally:
        connection.close()


@app.route("/companies/disclosures/ir/<int:document_id>/download")
def download_ir_document(document_id):
    connection = dashboard_db()
    try:
        document = queries.get_research_document(
            connection, document_id, document_type="ir"
        )
        if not document:
            abort(404)
        path = document_library.document_path(document["stored_filename"])
        if not path.is_file():
            abort(404)
        security_audit.log_event(
            connection,
            "PDF_DOWNLOAD",
            "ir_document",
            document_id,
            {
                "company_name": document.get("company_name"),
                "filename": document.get("original_filename"),
                "file_size": document.get("file_size"),
            },
        )
        connection.commit()
        return send_file(
            path,
            mimetype=document["mime_type"],
            as_attachment=True,
            download_name=document["original_filename"],
        )
    finally:
        connection.close()


@app.route("/companies/disclosures/ir/<int:document_id>/reanalyze", methods=["POST"])
@login_required
def reanalyze_ir_document(document_id):
    if session.get("role") != "admin":
        abort(403)
    if not validate_csrf(request.form.get("csrf_token", "")):
        return redirect(url_for("disclosures_page"))
    connection = dashboard_db()
    try:
        document = queries.get_research_document(
            connection, document_id, document_type="ir"
        )
        if not document:
            abort(404)
        analysis, error = ai_insights.analyze_research_document(
            connection, document, bypass_daily_limits=True
        )
        queries.update_research_document_analysis(
            connection,
            document_id,
            analysis=analysis,
            error_message=error,
            document_type="ir",
        )
        suggested_title = str((analysis or {}).get("suggested_title") or "").strip()[:200]
        filename_title = Path(str(document["original_filename"] or "")).stem.strip()
        current_title = str(document["title"] or "").strip()
        if suggested_title and filename_title and current_title == filename_title:
            queries.update_research_document_title(
                connection, document_id, suggested_title, document_type="ir"
            )
        notice = "IR AI 재분석이 완료되었습니다." if analysis else "IR AI 재분석에 실패했습니다."
        return redirect(url_for("disclosures_page", notice=notice))
    finally:
        connection.close()


@app.route("/companies/disclosures/ir/<int:document_id>/title", methods=["POST"])
@login_required
def update_ir_document_title(document_id):
    if session.get("role") != "admin":
        abort(403)
    if not validate_csrf(request.form.get("csrf_token", "")):
        return redirect(url_for("disclosures_page"))
    title = (request.form.get("title") or "").strip()
    if not title:
        return redirect(url_for("disclosures_page", notice="제목을 입력해주세요."))
    connection = dashboard_db()
    try:
        document = queries.get_research_document(
            connection, document_id, document_type="ir"
        )
        if not document:
            abort(404)
        title = title[:200]
        queries.update_research_document_title(
            connection, document_id, title, document_type="ir"
        )
        security_audit.log_event(
            connection,
            "IR_TITLE_UPDATE",
            "research_document",
            document_id,
            {"old_title": document.get("title"), "new_title": title},
        )
        connection.commit()
        return redirect(url_for("disclosures_page", notice="IR 자료 제목이 수정되었습니다."))
    finally:
        connection.close()


@app.route("/companies/disclosures/ir/<int:document_id>/delete", methods=["POST"])
@login_required
def delete_ir_document(document_id):
    if session.get("role") != "admin":
        abort(403)
    if not validate_csrf(request.form.get("csrf_token", "")):
        return redirect(url_for("disclosures_page"))
    connection = dashboard_db()
    try:
        document = queries.get_research_document(
            connection, document_id, document_type="ir"
        )
        if not document:
            abort(404)
        queries.delete_research_document(connection, document_id, document_type="ir")
        try:
            document_library.remove_file(document["stored_filename"])
        except OSError:
            logger.exception("삭제된 IR 자료의 파일 정리 실패: %s", document_id)
        return redirect(url_for("disclosures_page", notice="IR 자료를 삭제했습니다."))
    finally:
        connection.close()


# ============================================================
# 법률·규제
# ============================================================

@app.route("/laws")
def laws_page():
    connection = dashboard_db()
    try:
        updates = queries.list_recent_law_updates(connection, days=90)
        latest_law_sync = queries.get_latest_completed_run(connection, "law_sync")
        latest_law_row = connection.execute(
            "SELECT MAX(fetched_at) AS updated_at FROM law_updates"
        ).fetchone()
        latest_law_checked_at = (
            latest_law_sync.get("finished_at")
            if latest_law_sync
            else (latest_law_row["updated_at"] if latest_law_row else None)
        )
        monitored_laws = queries.list_monitored_laws(connection)
        for law in monitored_laws:
            law["source_url"] = f"https://www.law.go.kr/법령/{quote(law['law_name'])}"
        for update in updates:
            update["source_url"] = f"https://www.law.go.kr/법령/{quote(update['law_name'])}"
        return render_template(
            "laws.html",
            legal_section="laws",
            page_title="법령",
            page_description=(
                "카지노업 영업준칙과 모니터링 중인 현행 법령·최근 변경 이력을 "
                "확인합니다."
            ),
            updates=updates,
            monitored_laws=monitored_laws,
            casino_rules_url="https://www.law.go.kr/행정규칙/카지노업영업준칙",
            casino_rules_annex_url="https://www.law.go.kr/법령/관광진흥법시행규칙/제36조",
            checked_at=(
                official_document_manager.datetime_minute(latest_law_checked_at)
                if latest_law_checked_at else None
            ),
            changed_at=official_document_manager.datetime_minute(
                latest_law_row["updated_at"]
            ) if latest_law_row and latest_law_row["updated_at"] else None,
            check_status=latest_law_sync.get("status") if latest_law_sync else None,
        )
    finally:
        connection.close()


@app.route("/laws/fund-increase-scenarios")
def fund_increase_scenario_page():
    connection = dashboard_db()
    try:
        return render_template(
            "fund_increase_scenario.html",
            scenario=fund_increase_scenario.build_dashboard(
                connection, request.args.get("scenario")
            ),
        )
    finally:
        connection.close()


_TERMINAL_LEGISLATION_STAGES = (
    "폐기", "철회", "가결", "부결", "대안반영", "임기만료", "종료",
)


def _filter_legislation_items(
    government_notices, legislative_bills, *, source, status, importance, query
):
    """Combine and filter government notices and Assembly bills for the UI."""
    normalized_query = (query or "").casefold()
    items = []

    for original in government_notices:
        record = dict(original)
        item_status = "open" if record.get("is_open") else "closed"
        item_importance = "high" if item_status == "open" else "normal"
        searchable = " ".join(
            str(record.get(field) or "")
            for field in (
                "notice_name", "ministry_name", "law_type", "matched_keyword",
                "announcement_no",
            )
        ).casefold()
        record["legislation_status"] = item_status
        record["legislation_importance"] = item_importance
        items.append({
            "source": "government",
            "status": item_status,
            "importance": item_importance,
            "date": record.get("announcement_date") or "",
            "searchable": searchable,
            "record": record,
        })

    for original in legislative_bills:
        record = dict(original)
        stage_text = " ".join(
            str(record.get(field) or "")
            for field in ("process_stage", "pass_status")
        )
        item_status = (
            "closed"
            if any(marker in stage_text for marker in _TERMINAL_LEGISLATION_STAGES)
            else "open"
        )
        item_importance = (
            "high" if record.get("impact_level") == "high" else "normal"
        )
        searchable = " ".join(
            str(record.get(field) or "")
            for field in (
                "bill_name", "bill_no", "proposer_name", "committee_name",
                "matched_keyword", "process_stage", "pass_status",
            )
        ).casefold()
        record["legislation_status"] = item_status
        record["legislation_importance"] = item_importance
        items.append({
            "source": "assembly",
            "status": item_status,
            "importance": item_importance,
            "date": record.get("proposed_date") or "",
            "searchable": searchable,
            "record": record,
        })

    filtered = [
        item for item in items
        if (source == "all" or item["source"] == source)
        and (status == "all" or item["status"] == status)
        and (importance == "all" or item["importance"] == importance)
        and (not normalized_query or normalized_query in item["searchable"])
    ]
    return sorted(
        filtered,
        key=lambda item: re.sub(r"\D", "", item["date"]),
        reverse=True,
    )


@app.route("/laws/legislation")
def legislation_page():
    source_filter = request.args.get("source", "all").strip().lower()
    status_filter = request.args.get("status", "all").strip().lower()
    importance_filter = request.args.get("importance", "all").strip().lower()
    search_query = request.args.get("q", "").strip()[:100]
    if source_filter not in {"all", "government", "assembly"}:
        source_filter = "all"
    if status_filter not in {"all", "open", "closed"}:
        status_filter = "all"
    if importance_filter not in {"all", "high", "normal"}:
        importance_filter = "all"
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    page_size = 10

    connection = dashboard_db()
    try:
        all_legislative_bills = queries.list_legislative_bills(connection, limit=500)
        all_government_notices = queries.list_government_legislative_notices(
            connection, limit=500
        )
        legislation_items = _filter_legislation_items(
            all_government_notices,
            all_legislative_bills,
            source=source_filter,
            status=status_filter,
            importance=importance_filter,
            query=search_query,
        )
        total_count = len(legislation_items)
        total_pages = max(1, (total_count + page_size - 1) // page_size)
        page = min(page, total_pages)
        start = (page - 1) * page_size
        page_items = legislation_items[start:start + page_size]
        government_notices = [
            item["record"] for item in page_items if item["source"] == "government"
        ]
        legislative_bills = [
            item["record"] for item in page_items if item["source"] == "assembly"
        ]
        latest_law_sync = queries.get_latest_completed_run(connection, "law_sync")
        latest_government_sync = queries.get_latest_completed_run(
            connection, "government_notice_sync"
        )
        latest_sync = max(
            (run for run in (latest_law_sync, latest_government_sync) if run),
            key=lambda run: run.get("finished_at") or "",
            default=None,
        )
        changed_candidates = [
            _max_timestamp(connection, "legislative_bills", "updated_at"),
            _max_timestamp(
                connection,
                "government_legislative_notices",
                "updated_at",
            ),
        ]
        latest_changed_at = max(
            (value for value in changed_candidates if value),
            default=None,
        )
        return render_template(
            "laws.html",
            legal_section="legislation",
            page_title="입법동향",
            page_description=(
                "카지노 관련 정부입법예고와 국회 발의·심사 의안을 "
                "각각 확인합니다."
            ),
            legislative_bills=legislative_bills,
            government_notices=government_notices,
            legislation_filters={
                "source": source_filter,
                "status": status_filter,
                "importance": importance_filter,
                "q": search_query,
            },
            legislation_page=page,
            legislation_total_pages=total_pages,
            legislation_total_count=total_count,
            legislation_page_size=page_size,
            checked_at=(
                official_document_manager.datetime_minute(
                    latest_sync.get("finished_at")
                )
                if latest_sync and latest_sync.get("finished_at")
                else None
            ),
            changed_at=(
                official_document_manager.datetime_minute(latest_changed_at)
                if latest_changed_at
                else None
            ),
            check_status=(
                latest_sync.get("status") if latest_sync else None
            ),
        )
    finally:
        connection.close()


# ============================================================
# 회사 360도 비교
# ============================================================

COMPANY_BENEFIT_CATEGORIES = (
    ("family", "가족·보육"),
    ("financial", "금전·포인트"),
    ("health", "건강·의료"),
    ("leave", "휴가·근무"),
    ("meal", "식사·생활"),
    ("education", "교육·성장"),
    ("housing", "주거·교통"),
    ("other", "기타"),
)


def _company_benefit_form_values(connection, existing=None):
    company_name = " ".join((request.form.get("company_name") or "").split())
    valid_companies = {
        item["name"] for item in company_intelligence.list_company_options(connection)
    }
    if company_name not in valid_companies:
        raise ValueError("등록된 기업을 선택해주세요.")
    category = (request.form.get("category") or "other").strip()
    if category not in {value for value, _ in COMPANY_BENEFIT_CATEGORIES}:
        raise ValueError("복리후생 분류를 확인해주세요.")
    benefit_name = " ".join((request.form.get("benefit_name") or "").split())
    if not benefit_name or len(benefit_name) > 120:
        raise ValueError("복지명은 120자 이내로 입력해주세요.")

    values = {
        "company_name": company_name,
        "category": category,
        "benefit_name": benefit_name,
        "support_value": (request.form.get("support_value") or "").strip(),
        "benefit_level": (request.form.get("benefit_level") or "").strip(),
        "notes": (request.form.get("notes") or "").strip(),
        "effective_from": existing.get("effective_from") if existing else None,
        "ended_on": existing.get("ended_on") if existing else None,
    }
    limits = {"support_value": 300, "benefit_level": 100, "notes": 1000}
    if any(len(values[field]) > limit for field, limit in limits.items()):
        raise ValueError("지원 내용·수준·비고의 허용 길이를 초과했습니다.")
    return values


def _group_company_comment_threads(rows):
    grouped = {}
    roots = {}
    for item in rows:
        target_id = int(item["target_id"])
        grouped.setdefault(target_id, {"threads": [], "count": 0})
        if item["parent_id"] is None:
            thread = dict(item)
            thread["replies"] = []
            grouped[target_id]["threads"].append(thread)
            roots[item["id"]] = thread
    for item in rows:
        if item["parent_id"] is None or item["is_deleted"]:
            continue
        parent = roots.get(item["parent_id"])
        if parent and int(parent["target_id"]) == int(item["target_id"]):
            parent["replies"].append(dict(item))
    for target in grouped.values():
        target["threads"] = [
            thread for thread in target["threads"]
            if not thread["is_deleted"] or thread["replies"]
        ]
        target["count"] = sum(
            (0 if thread["is_deleted"] else 1) + len(thread["replies"])
            for thread in target["threads"]
        )
    return grouped


@app.get("/companies/benefits")
def company_benefits_page():
    selected_company = (request.args.get("company") or "").strip()
    connection = dashboard_db()
    try:
        if not membership.can_board(
            connection, "benefits", "read",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        companies = company_intelligence.list_company_options(connection)
        valid_names = {item["name"] for item in companies}
        if selected_company not in valid_names:
            selected_company = ""
        rows = queries.list_company_benefits(
            connection, selected_company or None
        )
        grouped = {item["name"]: [] for item in companies}
        for row in rows:
            grouped.setdefault(row["company_name"], []).append(row)
        visible_companies = [
            item for item in companies
            if not selected_company or item["name"] == selected_company
        ]
        return render_template(
            "company_benefits.html",
            companies=companies,
            visible_companies=visible_companies,
            benefits_by_company=grouped,
            selected_company=selected_company,
            benefit_categories=COMPANY_BENEFIT_CATEGORIES,
            category_labels=dict(COMPANY_BENEFIT_CATEGORIES),
            comments_by_target=_group_company_comment_threads(
                queries.list_company_content_comments(connection, "benefit")
            ),
            can_write=membership.can_board(
                connection, "benefits", "write",
                session.get("user_id"), session.get("role"),
            ),
            can_comment=membership.can_board(
                connection, "benefits", "comment",
                session.get("user_id"), session.get("role"),
            ),
            csrf_token=get_csrf_token(),
            today=today_kst_str(),
        )
    finally:
        connection.close()


@app.post("/companies/benefits")
@login_required
def create_company_benefit_route():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        if not membership.can_board(
            connection, "benefits", "write",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        values = _company_benefit_form_values(connection)
        queries.create_company_benefit(
            connection, values, actor_id=session.get("user_id")
        )
    except (ValueError, sqlite3.IntegrityError) as exc:
        connection.rollback()
        message = (
            "해당 기업에 같은 이름의 활성 복리후생이 이미 있습니다."
            if isinstance(exc, sqlite3.IntegrityError) else str(exc)
        )
        flash(message, "error")
    else:
        flash("복리후생 항목을 등록했습니다.", "success")
    finally:
        connection.close()
    return redirect(url_for(
        "company_benefits_page", company=request.form.get("company_name", "")
    ))


@app.post("/companies/benefits/<int:benefit_id>/edit")
@admin_required
def edit_company_benefit_route(benefit_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        benefit = queries.get_company_benefit(connection, benefit_id)
        if not benefit:
            abort(404)
        values = _company_benefit_form_values(connection, existing=benefit)
        queries.update_company_benefit(connection, benefit_id, values)
    except (ValueError, sqlite3.IntegrityError) as exc:
        connection.rollback()
        message = (
            "해당 기업에 같은 이름의 활성 복리후생이 이미 있습니다."
            if isinstance(exc, sqlite3.IntegrityError) else str(exc)
        )
        flash(message, "error")
    else:
        flash("복리후생 항목을 수정했습니다.", "success")
    finally:
        connection.close()
    return redirect(url_for(
        "company_benefits_page", company=request.form.get("company_name", "")
    ))


@app.post("/companies/benefits/<int:benefit_id>/end")
@admin_required
def end_company_benefit_route(benefit_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    ended_on = (request.form.get("ended_on") or today_kst_str()).strip()
    try:
        datetime.strptime(ended_on, "%Y-%m-%d")
    except ValueError:
        abort(400)
    connection = dashboard_db()
    try:
        benefit = queries.get_company_benefit(connection, benefit_id)
        if not benefit:
            abort(404)
        if benefit.get("effective_from") and ended_on < benefit["effective_from"]:
            flash("종료일은 시행일보다 빠를 수 없습니다.", "error")
        else:
            queries.end_company_benefit(connection, benefit_id, ended_on)
            flash("복리후생 종료 이력을 남겼습니다.", "success")
    finally:
        connection.close()
    return redirect(url_for(
        "company_benefits_page", company=request.form.get("company_name", "")
    ))


RECRUITMENT_GUIDE_PROCESS_TYPES = (
    ("interview", "면접"),
    ("practical", "실기"),
    ("written", "필기"),
    ("other", "기타"),
)


def _recruitment_guide_form_values(connection):
    company_name = " ".join((request.form.get("company_name") or "").split())
    valid_companies = {
        item["name"] for item in company_intelligence.list_company_options(connection)
    }
    if company_name not in valid_companies:
        raise ValueError("등록된 기업을 선택해주세요.")
    process_type = (request.form.get("process_type") or "").strip()
    if process_type not in {value for value, _ in RECRUITMENT_GUIDE_PROCESS_TYPES}:
        raise ValueError("전형 종류를 확인해주세요.")
    question_text = (request.form.get("question_text") or "").strip()
    if not question_text:
        raise ValueError("실제 질문을 입력해주세요.")
    experience_period = (request.form.get("experience_period") or "").strip()
    if experience_period:
        try:
            datetime.strptime(experience_period, "%Y-%m")
        except ValueError as exc:
            raise ValueError("응시 시기를 확인해주세요.") from exc
    values = {
        "company_name": company_name,
        "process_type": process_type,
        "position_name": " ".join((request.form.get("position_name") or "").split()),
        "stage_name": " ".join((request.form.get("stage_name") or "").split()),
        "question_text": question_text,
        "atmosphere": (request.form.get("atmosphere") or "").strip(),
        "experience_period": experience_period,
        "notes": (request.form.get("notes") or "").strip(),
    }
    limits = {
        "position_name": 120,
        "stage_name": 100,
        "question_text": 2000,
        "atmosphere": 1000,
        "notes": 1500,
    }
    if any(len(values[field]) > limit for field, limit in limits.items()):
        raise ValueError("입력 가능한 글자 수를 초과했습니다.")
    return values


@app.get("/companies/recruitment-guide")
def company_recruitment_guide_page():
    selected_company = (request.args.get("company") or "").strip()
    selected_process = (request.args.get("process_type") or "").strip()
    connection = dashboard_db()
    try:
        if not membership.can_board(
            connection, "recruitment_guide", "read",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        companies = company_intelligence.list_company_options(connection)
        valid_names = {item["name"] for item in companies}
        valid_processes = {value for value, _ in RECRUITMENT_GUIDE_PROCESS_TYPES}
        if selected_company not in valid_names:
            selected_company = ""
        if selected_process not in valid_processes:
            selected_process = ""
        rows = queries.list_company_recruitment_guides(
            connection, selected_company or None, selected_process or None
        )
        grouped = {item["name"]: [] for item in companies}
        for row in rows:
            grouped.setdefault(row["company_name"], []).append(row)
        visible_companies = [
            item for item in companies
            if not selected_company or item["name"] == selected_company
        ]
        return render_template(
            "company_recruitment_guide.html",
            companies=companies,
            visible_companies=visible_companies,
            guides_by_company=grouped,
            selected_company=selected_company,
            selected_process=selected_process,
            process_types=RECRUITMENT_GUIDE_PROCESS_TYPES,
            process_labels=dict(RECRUITMENT_GUIDE_PROCESS_TYPES),
            comments_by_target=_group_company_comment_threads(
                queries.list_company_content_comments(
                    connection, "recruitment_guide"
                )
            ),
            can_write=membership.can_board(
                connection, "recruitment_guide", "write",
                session.get("user_id"), session.get("role"),
            ),
            can_comment=membership.can_board(
                connection, "recruitment_guide", "comment",
                session.get("user_id"), session.get("role"),
            ),
            csrf_token=get_csrf_token(),
        )
    finally:
        connection.close()


@app.post("/companies/recruitment-guide")
@login_required
def create_company_recruitment_guide_route():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        if not membership.can_board(
            connection, "recruitment_guide", "write",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        values = _recruitment_guide_form_values(connection)
        queries.create_company_recruitment_guide(
            connection, values, actor_id=session.get("user_id")
        )
    except (ValueError, sqlite3.IntegrityError) as exc:
        connection.rollback()
        message = (
            "같은 기업·전형·응시 시기에 동일한 질문이 이미 있습니다."
            if isinstance(exc, sqlite3.IntegrityError) else str(exc)
        )
        flash(message, "error")
    else:
        flash("채용 족보 항목을 등록했습니다.", "success")
    finally:
        connection.close()
    return redirect(url_for(
        "company_recruitment_guide_page",
        company=request.form.get("company_name", ""),
    ))


@app.post("/companies/recruitment-guide/<int:guide_id>/edit")
@admin_required
def edit_company_recruitment_guide_route(guide_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        if not queries.get_company_recruitment_guide(connection, guide_id):
            abort(404)
        values = _recruitment_guide_form_values(connection)
        queries.update_company_recruitment_guide(connection, guide_id, values)
    except (ValueError, sqlite3.IntegrityError) as exc:
        connection.rollback()
        message = (
            "같은 기업·전형·응시 시기에 동일한 질문이 이미 있습니다."
            if isinstance(exc, sqlite3.IntegrityError) else str(exc)
        )
        flash(message, "error")
    else:
        flash("채용 족보 항목을 수정했습니다.", "success")
    finally:
        connection.close()
    return redirect(url_for(
        "company_recruitment_guide_page",
        company=request.form.get("company_name", ""),
    ))


def _company_comment_target(connection, target_type, target_id):
    if target_type == "benefit":
        return queries.get_company_benefit(connection, target_id)
    if target_type == "recruitment_guide":
        return queries.get_company_recruitment_guide(connection, target_id)
    return None


def _company_comment_redirect(target_type, target):
    endpoint = (
        "company_benefits_page"
        if target_type == "benefit"
        else "company_recruitment_guide_page"
    )
    return url_for(endpoint, company=target["company_name"]) + f"#comments-{target_type}-{target['id']}"


@app.post("/companies/comments/<target_type>/<int:target_id>")
@login_required
def create_company_content_comment_route(target_type, target_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    parent_value = (request.form.get("parent_id") or "").strip()
    if parent_value and not parent_value.isdigit():
        abort(400)
    parent_id = int(parent_value) if parent_value else None
    connection = dashboard_db()
    try:
        board_key = {
            "benefit": "benefits",
            "recruitment_guide": "recruitment_guide",
        }.get(target_type)
        if not board_key or not membership.can_board(
            connection, board_key, "comment",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        target = _company_comment_target(connection, target_type, target_id)
        if not target:
            abort(404)
        try:
            comment_id = queries.create_company_content_comment(
                connection,
                target_type=target_type,
                target_id=target_id,
                author_id=session["user_id"],
                author_username=session.get("username") or "",
                content=request.form.get("content"),
                parent_id=parent_id,
            )
        except ValueError as exc:
            flash(str(exc), "error")
        else:
            security_audit.log_event(
                connection,
                "COMPANY_CONTENT_COMMENT_CREATE",
                "company_content_comment",
                comment_id,
                {
                    "target_type": target_type,
                    "target_id": target_id,
                    "is_reply": parent_id is not None,
                },
            )
            connection.commit()
        return redirect(_company_comment_redirect(target_type, target))
    finally:
        connection.close()


@app.post("/companies/comments/<target_type>/<int:target_id>/<int:comment_id>/delete")
@login_required
def delete_company_content_comment_route(target_type, target_id, comment_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        target = _company_comment_target(connection, target_type, target_id)
        comment = queries.get_company_content_comment(connection, comment_id)
        if (
            not target or not comment or comment["is_deleted"]
            or comment["target_type"] != target_type
            or int(comment["target_id"]) != target_id
        ):
            abort(404)
        is_owner = int(comment["author_id"]) == int(session["user_id"])
        if session.get("role") != "admin" and not is_owner:
            abort(403)
        queries.soft_delete_company_content_comment(
            connection, comment_id, session["user_id"]
        )
        security_audit.log_event(
            connection,
            "COMPANY_CONTENT_COMMENT_DELETE",
            "company_content_comment",
            comment_id,
            {"target_type": target_type, "target_id": target_id},
        )
        connection.commit()
        return redirect(_company_comment_redirect(target_type, target))
    finally:
        connection.close()

@app.route("/companies")
def companies_page():
    try:
        days = max(30, min(int(request.args.get("days", 90)), 365))
    except (TypeError, ValueError):
        days = 90
    connection = dashboard_db()
    try:
        companies = company_intelligence.build_company_comparison(connection, days=days)
        for company in companies:
            company["display_name"] = company_intelligence.company_display_name(
                company["name"], g.locale
            )
            company["display_aliases"] = company_intelligence.company_display_aliases(
                company.get("aliases", []), g.locale
            )
        return render_template("companies.html", companies=companies, days=days)
    finally:
        connection.close()


@app.route("/companies/comparison")
def company_comparison_page():
    connection = dashboard_db()
    try:
        return render_template(
            "company_comparison.html",
            comparison=company_comparison.build_dashboard(
                connection,
                request.args.get("year"),
                request.args.get("metric"),
                request.args.get("include_kangwon") == "1",
                request.args.get("period"),
            ),
        )
    finally:
        connection.close()


@app.route("/companies/expert")
def company_expert_page():
    connection = dashboard_db()
    try:
        return render_template(
            "company_expert.html",
            dashboard=company_expert.build_dashboard(
                connection, request.args.get("company")
            ),
        )
    finally:
        connection.close()


@app.route("/companies/<string:company_slug>")
@login_required
def company_detail_page(company_slug):
    connection = dashboard_db()
    try:
        context = company_intelligence.build_company_detail_context(
            connection, company_slug
        )
        if not context:
            abort(404)
        company = context["company"]
        context.update(
            {
                "company_name": company["name"],
                "company_aliases_display": company_intelligence.company_display_aliases(
                    company.get("aliases", []), g.locale
                ),
            }
        )
        if g.locale == "en":
            context["company_display_name"] = company_intelligence.company_display_name(
                company["name"], g.locale
            )
        return render_template("company_detail.html", **context)
    finally:
        connection.close()


@app.get("/companies/news")
def company_news_page():
    """AI 분류 신호를 우선해 회사별 국내 뉴스를 대시보드로 제공한다."""

    try:
        days = max(30, min(int(request.args.get("days", 90)), 365))
    except (TypeError, ValueError):
        days = 90
    selected_company = (request.args.get("company") or "").strip()
    selected_category = (request.args.get("category") or "all").strip()
    search_query = (request.args.get("q") or "").strip()[:100]
    selected_importance = (request.args.get("importance") or "all").strip()
    selected_analysis = (request.args.get("analysis") or "all").strip()
    selected_impact = (request.args.get("impact") or "all").strip()
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    category_labels = {
        "all": "전체",
        **company_intelligence.COMPANY_NEWS_CATEGORY_LABELS,
    }
    if selected_category not in category_labels:
        selected_category = "all"
    if selected_importance not in {"all", "important", "regular"}:
        selected_importance = "all"
    if selected_analysis not in {"all", "analyzed", "pending"}:
        selected_analysis = "all"
    if selected_impact not in {"all", "positive", "negative", "mixed", "neutral"}:
        selected_impact = "all"

    connection = dashboard_db()
    try:
        company_news = company_intelligence.build_company_news_dashboard(
            connection, days=days
        )
        if g.locale == "en":
            for company in company_news:
                company["articles"] = content_translation.apply_cached(
                    connection,
                    "news",
                    company["articles"],
                    id_field="article_id",
                )
        company_names = [company["name"] for company in company_news]
        company_name_labels = {
            company["name"]: company_intelligence.company_display_name(
                company["name"], g.locale
            )
            for company in company_news
        }
        if selected_company not in company_names:
            selected_company = ""

        selected_company_articles = [
            item
            for company in company_news
            if not selected_company or company["name"] == selected_company
            for item in company["articles"]
        ]
        news_stats = {
            "total": len(selected_company_articles),
            "important": sum(item["is_important"] for item in selected_company_articles),
            "analyzed": sum(item["is_analyzed"] for item in selected_company_articles),
            "negative": sum(item["impact_code"] == "negative" for item in selected_company_articles),
        }

        def matches_view_filters(item, include_category=True):
            searchable = " ".join(
                str(item.get(key) or "")
                for key in ("title", "publisher", "latest_summary", "category")
            ).casefold()
            if search_query and search_query.casefold() not in searchable:
                return False
            if include_category and selected_category != "all" and item["category_code"] != selected_category:
                return False
            if selected_importance == "important" and not item["is_important"]:
                return False
            if selected_importance == "regular" and item["is_important"]:
                return False
            if selected_analysis == "analyzed" and not item["is_analyzed"]:
                return False
            if selected_analysis == "pending" and item["is_analyzed"]:
                return False
            if selected_impact != "all" and item["impact_code"] != selected_impact:
                return False
            return True

        visible_companies = []
        for company in company_news:
            if selected_company and company["name"] != selected_company:
                continue
            articles = company["articles"]
            articles = [item for item in articles if matches_view_filters(item)]
            visible_companies.append(
                {
                    **company,
                    "display_name": company_name_labels[company["name"]],
                    "display_aliases": company_intelligence.company_display_aliases(
                        company["aliases"], g.locale
                    ),
                    "visible_articles": articles,
                }
            )

        category_counts = {
            code: sum(
                1
                for item in selected_company_articles
                if matches_view_filters(item, include_category=False)
                and (code == "all" or item["category_code"] == code)
            )
            for code in category_labels
        }
        page_size = 20
        visible_total = sum(
            len(company["visible_articles"]) for company in visible_companies
        )
        page_count = max(1, (visible_total + page_size - 1) // page_size)
        page = min(page, page_count)
        page_start = (page - 1) * page_size
        page_end = page_start + page_size
        cursor = 0
        paged_companies = []
        for company in visible_companies:
            articles = company["visible_articles"]
            company_start = cursor
            company_end = cursor + len(articles)
            slice_start = max(0, page_start - company_start)
            slice_end = min(len(articles), page_end - company_start)
            cursor = company_end
            if slice_start >= slice_end:
                continue
            paged_companies.append(
                {**company, "visible_articles": articles[slice_start:slice_end]}
            )
        return render_template(
            "company_news.html",
            companies=paged_companies,
            company_names=company_names,
            company_name_labels=company_name_labels,
            selected_company=selected_company,
            selected_category=selected_category,
            search_query=search_query,
            selected_importance=selected_importance,
            selected_analysis=selected_analysis,
            selected_impact=selected_impact,
            category_labels=category_labels,
            category_counts=category_counts,
            news_stats=news_stats,
            days=days,
            news_page=page,
            news_page_count=page_count,
            news_total_count=visible_total,
        )
    finally:
        connection.close()


def _community_board_context(
    connection, page=1, error=None, form_data=None, board_type="community",
):
    page_size = 20
    total = queries.count_community_posts(connection, board_type=board_type)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(int(page), total_pages))
    return {
        "posts": queries.list_community_posts(
            connection, limit=page_size, offset=(page - 1) * page_size,
            board_type=board_type,
        ),
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "csrf_token": get_csrf_token(),
        "error": error,
        "form_data": form_data or {},
        "board_type": board_type,
        "is_notice_board": board_type == "notice",
        "can_write": membership.can_board(
            connection, board_type, "write",
            session.get("user_id"), session.get("role"),
        ),
        "create_endpoint": (
            "create_notice_post_route"
            if board_type == "notice"
            else "create_community_post_route"
        ),
    }


_COMMUNITY_MARKDOWN_TAGS = {
    "p", "br", "strong", "em", "del", "blockquote", "code", "pre",
    "ul", "ol", "li", "h1", "h2", "h3", "h4", "hr", "table",
    "thead", "tbody", "tr", "th", "td", "a", "img",
}
_COMMUNITY_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif"}


def _render_community_markdown(value):
    rendered = markdown.markdown(
        value or "",
        extensions=["fenced_code", "tables", "sane_lists", "nl2br"],
        output_format="html",
    )
    cleaned = bleach.clean(
        rendered,
        tags=_COMMUNITY_MARKDOWN_TAGS,
        attributes={"a": ["href", "title"], "img": ["src", "alt", "title"]},
        protocols={"https", "mailto"},
        strip=True,
    )
    return Markup(cleaned)


def _community_viewer_hash():
    if session.get("user_id"):
        identity = f"user:{session['user_id']}"
    else:
        identity = (
            f"anonymous:{request.remote_addr or ''}:"
            f"{(request.headers.get('User-Agent') or '')[:500]}"
        )
    secret = str(app.secret_key or config.FLASK_SECRET_KEY).encode("utf-8")
    return hmac.new(secret, identity.encode("utf-8"), hashlib.sha256).hexdigest()


@app.post("/editor/images")
@login_required
def upload_editor_image_route():
    if not validate_csrf(request.form.get("csrf_token", "")):
        return jsonify({"error": "요청이 만료되었습니다. 새로고침 후 다시 시도해주세요."}), 400
    scope = (request.form.get("scope") or "").strip()
    if scope not in {"community", "notice", "tips", "bug_report"}:
        return jsonify({"error": "허용되지 않은 작성 화면입니다."}), 400
    if scope == "tips" and session.get("role") != "admin":
        abort(403)
    board_key = {"community": "community", "notice": "notice", "bug_report": "bug_reports"}.get(scope)
    if board_key:
        access_connection = dashboard_db()
        try:
            if not membership.can_board(
                access_connection, board_key, "write",
                session.get("user_id"), session.get("role"),
            ):
                abort(403)
        finally:
            access_connection.close()
    try:
        filename = editor_images.save_pasted_image(
            request.files.get("image"),
            config.EDITOR_IMAGE_DIR,
            config.EDITOR_IMAGE_MAX_BYTES,
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    image_url = url_for("static", filename=f"uploads/editor/{filename}")
    connection = dashboard_db()
    try:
        security_audit.log_event(
            connection, "EDITOR_IMAGE_UPLOAD", "editor_image", filename,
            {"scope": scope},
        )
        connection.commit()
    finally:
        connection.close()
    return jsonify({"url": image_url})


def _community_attachment_url(raw_value, kind):
    value = (raw_value or "").strip()
    if not value:
        return None
    if len(value) > 2048:
        raise ValueError("첨부 링크가 너무 깁니다.")
    try:
        parts = urlsplit(value)
        _ = parts.port
    except ValueError as error:
        raise ValueError("올바른 첨부 링크를 입력해주세요.") from error
    if parts.scheme.lower() != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("첨부 링크는 사용자 정보가 없는 HTTPS 주소만 사용할 수 있습니다.")
    suffix = Path(parts.path).suffix.casefold()
    if kind == "image" and suffix not in _COMMUNITY_IMAGE_EXTENSIONS:
        raise ValueError("이미지 링크는 PNG, JPG, GIF, WEBP, AVIF 형식만 사용할 수 있습니다.")
    if kind == "pdf" and suffix != ".pdf":
        raise ValueError("PDF 링크는 .pdf로 끝나는 HTTPS 주소만 사용할 수 있습니다.")
    return value


_DIARY_MOODS = {
    "ecstatic": ("🤩", "황홀함"),
    "great": ("😄", "아주 좋음"),
    "happy": ("😊", "행복함"),
    "good": ("🙂", "좋음"),
    "proud": ("🥹", "뿐듯함"),
    "grateful": ("🙏", "감사함"),
    "loved": ("🥰", "사랑받는 기분"),
    "excited": ("🥳", "신남"),
    "hopeful": ("🌱", "희망참"),
    "motivated": ("🔥", "의욕 넘침"),
    "focused": ("🎯", "집중됨"),
    "confident": ("💪", "자신감 있음"),
    "refreshed": ("✨", "개운함"),
    "calm": ("😌", "평온함"),
    "comfortable": ("🤗", "편안함"),
    "content": ("☺️", "만족스러움"),
    "neutral": ("😐", "그저 그럼"),
    "thoughtful": ("🤔", "생각이 많음"),
    "curious": ("🧐", "궁금함"),
    "surprised": ("😮", "놀람"),
    "confused": ("😵‍💫", "혼란스러움"),
    "bored": ("🫥", "지루함"),
    "tired": ("😮‍💨", "피곤함"),
    "sleepy": ("😴", "졸림"),
    "overwhelmed": ("🤯", "벅참"),
    "anxious": ("😰", "불안함"),
    "worried": ("😟", "걱정됨"),
    "frustrated": ("😣", "답답함"),
    "angry": ("😠", "화남"),
    "lonely": ("🫠", "외로움"),
    "sad": ("😔", "속상함"),
    "hurt": ("😢", "마음 아픔"),
    "exhausted": ("🪫", "지침"),
}


def _diary_form_data(source):
    diary_date = (source.get("diary_date") or "").strip()
    mood_code = (source.get("mood_code") or "").strip()
    title = (source.get("title") or "").strip()
    content = (source.get("content") or "").strip()
    try:
        datetime.strptime(diary_date, "%Y-%m-%d")
    except ValueError as error:
        raise ValueError("날짜를 올바르게 선택해주세요.") from error
    if mood_code not in _DIARY_MOODS:
        raise ValueError("오늘의 기분을 선택해주세요.")
    return {
        "diary_date": diary_date,
        "mood_code": mood_code,
        "title": title,
        "content": content,
    }


def _diary_board_context(connection, page=1, error=None, form_data=None):
    page_size = 20
    owner_id = session["user_id"]
    total = queries.count_diary_entries(connection, owner_id)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(int(page), total_pages))
    return {
        "entries": queries.list_diary_entries(
            connection, owner_id, page_size, (page - 1) * page_size
        ),
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "moods": _DIARY_MOODS,
        "csrf_token": get_csrf_token(),
        "error": error,
        "form_data": form_data or {"diary_date": today_kst_str(), "mood_code": "calm"},
    }


@app.route("/board/diary", methods=["GET", "POST"])
@login_required
def diary_board_page():
    connection = dashboard_db()
    try:
        try:
            page = int(request.args.get("page", 1))
        except (TypeError, ValueError):
            page = 1
        if request.method == "GET":
            return render_template(
                "diary_board.html", **_diary_board_context(connection, page=page)
            )
        raw_form = {
            key: (request.form.get(key) or "")
            for key in ("diary_date", "mood_code", "title", "content")
        }
        if not validate_csrf(request.form.get("csrf_token", "")):
            return render_template(
                "diary_board.html",
                **_diary_board_context(
                    connection, error="요청이 만료되었습니다. 다시 시도해주세요.",
                    form_data=raw_form,
                ),
            ), 400
        try:
            form_data = _diary_form_data(raw_form)
            entry_id = queries.create_diary_entry(
                connection,
                session["user_id"],
                session.get("username") or "",
                **form_data,
            )
        except ValueError as error:
            return render_template(
                "diary_board.html",
                **_diary_board_context(
                    connection, error=str(error), form_data=raw_form
                ),
            ), 400
        security_audit.log_event(
            connection, "DIARY_ENTRY_CREATE", "diary_entry", entry_id,
            {"diary_date": form_data["diary_date"]},
        )
        connection.commit()
        return redirect(url_for("diary_entry_page", entry_id=entry_id))
    finally:
        connection.close()


@app.get("/board/diary/<int:entry_id>")
@login_required
def diary_entry_page(entry_id):
    connection = dashboard_db()
    try:
        entry = queries.get_diary_entry(connection, entry_id, session["user_id"])
        if not entry:
            abort(404)
        return render_template(
            "diary_entry.html", entry=entry,
            mood=_DIARY_MOODS.get(entry.get("mood_code"), ("•", "미선택")),
            entry_html=_render_community_markdown(entry["content"]),
            csrf_token=get_csrf_token(),
        )
    finally:
        connection.close()


@app.route("/board/diary/<int:entry_id>/edit", methods=["GET", "POST"])
@login_required
def edit_diary_entry_route(entry_id):
    connection = dashboard_db()
    try:
        entry = queries.get_diary_entry(connection, entry_id, session["user_id"])
        if not entry:
            abort(404)
        error = None
        status = 200
        form_data = entry
        if request.method == "POST":
            raw_form = {
                key: (request.form.get(key) or "")
                for key in ("diary_date", "mood_code", "title", "content")
            }
            form_data = raw_form
            if not validate_csrf(request.form.get("csrf_token", "")):
                error = "요청이 만료되었습니다. 다시 시도해주세요."
                status = 400
            else:
                try:
                    clean = _diary_form_data(raw_form)
                    queries.update_diary_entry(
                        connection, entry_id, session["user_id"], **clean
                    )
                except ValueError as exc:
                    error = str(exc)
                    status = 400
                else:
                    security_audit.log_event(
                        connection, "DIARY_ENTRY_UPDATE", "diary_entry", entry_id
                    )
                    connection.commit()
                    return redirect(url_for("diary_entry_page", entry_id=entry_id))
        return render_template(
            "diary_edit.html", entry=entry, form_data=form_data, moods=_DIARY_MOODS,
            error=error, csrf_token=get_csrf_token(),
        ), status
    finally:
        connection.close()


@app.post("/board/diary/<int:entry_id>/delete")
@login_required
def delete_diary_entry_route(entry_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        try:
            queries.delete_diary_entry(connection, entry_id, session["user_id"])
        except ValueError:
            abort(404)
        security_audit.log_event(
            connection, "DIARY_ENTRY_DELETE", "diary_entry", entry_id
        )
        connection.commit()
        return redirect(url_for("diary_board_page"))
    finally:
        connection.close()


@app.post("/board/diary/images")
@login_required
def upload_diary_image_route():
    if not validate_csrf(request.form.get("csrf_token", "")):
        return jsonify({"error": "요청이 만료되었습니다. 새로고침 후 다시 시도해주세요."}), 400
    try:
        filename = editor_images.save_pasted_image(
            request.files.get("image"), config.DIARY_IMAGE_DIR,
            config.DIARY_IMAGE_MAX_BYTES,
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    connection = dashboard_db()
    try:
        try:
            queries.register_diary_image(connection, filename, session["user_id"])
            security_audit.log_event(
                connection, "DIARY_IMAGE_UPLOAD", "diary_image", filename
            )
            connection.commit()
        except Exception:
            (Path(config.DIARY_IMAGE_DIR) / filename).unlink(missing_ok=True)
            raise
    finally:
        connection.close()
    return jsonify({"url": url_for("diary_image_file", filename=filename)})


@app.get("/board/diary/images/<filename>")
@login_required
def diary_image_file(filename):
    if not re.fullmatch(r"[0-9a-f]{32}\.(?:png|jpg|gif|webp)", filename):
        abort(404)
    connection = dashboard_db()
    try:
        if not queries.diary_image_owned_by(connection, filename, session["user_id"]):
            abort(404)
    finally:
        connection.close()
    path = Path(config.DIARY_IMAGE_DIR) / filename
    if not path.is_file():
        abort(404)
    return send_file(path, conditional=True, max_age=0)


@app.get("/board")
def community_board_page():
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    connection = dashboard_db()
    try:
        if not membership.can_board(
            connection, "community", "read",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        return render_template(
            "community_board.html",
            **_community_board_context(connection, page=page),
        )
    finally:
        connection.close()


@app.get("/board/notices")
def notice_board_page():
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    connection = dashboard_db()
    try:
        if not membership.can_board(
            connection, "notice", "read",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        return render_template(
            "community_board.html",
            **_community_board_context(
                connection, page=page, board_type="notice"
            ),
        )
    finally:
        connection.close()


@app.post("/board")
@login_required
def create_community_post_route():
    connection = dashboard_db()
    try:
        if not membership.can_board(
            connection, "community", "write",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        form_data = {
            "title": (request.form.get("title") or "").strip(),
            "content": (request.form.get("content") or "").strip(),
            "image_url": (request.form.get("image_url") or "").strip(),
            "pdf_url": (request.form.get("pdf_url") or "").strip(),
            "is_pinned": request.form.get("is_pinned") == "1",
        }
        if not validate_csrf(request.form.get("csrf_token", "")):
            return render_template(
                "community_board.html",
                **_community_board_context(
                    connection,
                    error="요청이 만료되었습니다. 다시 시도해주세요.",
                    form_data=form_data,
                ),
            ), 400
        try:
            image_url = _community_attachment_url(form_data["image_url"], "image")
            pdf_url = _community_attachment_url(form_data["pdf_url"], "pdf")
            post_id = queries.create_community_post(
                connection,
                author_id=session["user_id"],
                author_username=session.get("username") or "",
                title=form_data["title"],
                content=form_data["content"],
                image_url=image_url,
                pdf_url=pdf_url,
                board_type="community",
                is_pinned=(
                    session.get("role") == "admin" and form_data["is_pinned"]
                ),
            )
        except ValueError as error:
            return render_template(
                "community_board.html",
                **_community_board_context(
                    connection, error=str(error), form_data=form_data
                ),
            ), 400
        security_audit.log_event(
            connection,
            "COMMUNITY_PINNED_POST_CREATE"
            if form_data["is_pinned"] and session.get("role") == "admin"
            else "COMMUNITY_POST_CREATE",
            "community_post",
            post_id,
            {"title_length": len(form_data["title"])},
        )
        connection.commit()
        return redirect(url_for("community_post_page", post_id=post_id))
    finally:
        connection.close()


@app.post("/board/notices")
@admin_required
def create_notice_post_route():
    connection = dashboard_db()
    try:
        if not membership.can_board(
            connection, "notice", "write",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        form_data = {
            "title": (request.form.get("title") or "").strip(),
            "content": (request.form.get("content") or "").strip(),
            "image_url": (request.form.get("image_url") or "").strip(),
            "pdf_url": (request.form.get("pdf_url") or "").strip(),
        }
        if not validate_csrf(request.form.get("csrf_token", "")):
            return render_template(
                "community_board.html",
                **_community_board_context(
                    connection, error="요청이 만료되었습니다. 다시 시도해주세요.",
                    form_data=form_data, board_type="notice",
                ),
            ), 400
        try:
            image_url = _community_attachment_url(form_data["image_url"], "image")
            pdf_url = _community_attachment_url(form_data["pdf_url"], "pdf")
            post_id = queries.create_community_post(
                connection,
                author_id=session["user_id"],
                author_username=session.get("username") or "",
                title=form_data["title"],
                content=form_data["content"],
                image_url=image_url,
                pdf_url=pdf_url,
                board_type="notice",
            )
        except ValueError as error:
            return render_template(
                "community_board.html",
                **_community_board_context(
                    connection, error=str(error), form_data=form_data,
                    board_type="notice",
                ),
            ), 400
        security_audit.log_event(
            connection, "NOTICE_POST_CREATE", "community_post", post_id,
            {"title_length": len(form_data["title"])},
        )
        connection.commit()
        return redirect(url_for("community_post_page", post_id=post_id))
    finally:
        connection.close()


@app.get("/board/<int:post_id>")
def community_post_page(post_id):
    connection = dashboard_db()
    try:
        post = queries.get_community_post(
            connection, post_id, user_id=session.get("user_id")
        )
        if not post:
            abort(404)
        if post["board_type"] == "diary":
            abort(404)
        if not membership.can_board(
            connection, post["board_type"], "read",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        queries.record_unique_community_post_view(
            connection, post_id, _community_viewer_hash()
        )
        post = queries.get_community_post(
            connection, post_id, user_id=session.get("user_id")
        )
        return render_template(
            "community_post.html",
            post=post,
            post_html=_render_community_markdown(post["content"]),
            comments=queries.list_community_comments(connection, post_id),
            can_comment=membership.can_board(
                connection, post["board_type"], "comment",
                session.get("user_id"), session.get("role"),
            ),
            csrf_token=get_csrf_token(),
            comment_error=None,
            comment_content="",
        )
    finally:
        connection.close()


@app.route("/board/<int:post_id>/edit", methods=["GET", "POST"])
@login_required
def edit_community_post_route(post_id):
    connection = dashboard_db()
    try:
        post = queries.get_community_post(connection, post_id)
        if not post:
            abort(404)
        if post["board_type"] == "diary":
            abort(404)
        if not membership.can_board(
            connection, post["board_type"], "write",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        is_admin = session.get("role") == "admin"
        is_owner = int(post["author_id"]) == int(session["user_id"])
        if (post["board_type"] == "notice" and not is_admin) or (
            post["board_type"] == "community" and not (is_admin or is_owner)
        ):
            abort(403)
        form_data = {
            "title": post["title"], "content": post["content"],
            "image_url": post.get("image_url") or "",
            "pdf_url": post.get("pdf_url") or "",
            "is_pinned": bool(post.get("is_pinned")),
        }
        error = None
        status = 200
        if request.method == "POST":
            form_data = {
                "title": (request.form.get("title") or "").strip(),
                "content": (request.form.get("content") or "").strip(),
                "image_url": (request.form.get("image_url") or "").strip(),
                "pdf_url": (request.form.get("pdf_url") or "").strip(),
                "is_pinned": request.form.get("is_pinned") == "1",
            }
            if not validate_csrf(request.form.get("csrf_token", "")):
                error = "요청이 만료되었습니다. 다시 시도해주세요."
                status = 400
            else:
                try:
                    image_url = _community_attachment_url(form_data["image_url"], "image")
                    pdf_url = _community_attachment_url(form_data["pdf_url"], "pdf")
                    queries.update_community_post(
                        connection, post_id, form_data["title"], form_data["content"],
                        image_url=image_url, pdf_url=pdf_url,
                        is_pinned=(form_data["is_pinned"] if is_admin else None),
                    )
                except ValueError as exc:
                    error = str(exc)
                    status = 400
                else:
                    security_audit.log_event(
                        connection,
                        "NOTICE_POST_UPDATE" if post["board_type"] == "notice"
                        else "COMMUNITY_POST_UPDATE",
                        "community_post", post_id,
                        {"board_type": post["board_type"], "owner_edit": is_owner},
                    )
                    connection.commit()
                    return redirect(url_for("community_post_page", post_id=post_id))
        return render_template(
            "community_post_edit.html", post=post, form_data=form_data,
            error=error, csrf_token=get_csrf_token(),
        ), status
    finally:
        connection.close()


@app.post("/board/<int:post_id>/comments")
@login_required
def create_community_comment_route(post_id):
    connection = dashboard_db()
    try:
        post = queries.get_community_post(
            connection, post_id, user_id=session.get("user_id")
        )
        if not post:
            abort(404)
        if post["board_type"] == "diary":
            abort(404)
        if not membership.can_board(
            connection, post["board_type"], "comment",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        content = (request.form.get("content") or "").strip()
        error = None
        if not validate_csrf(request.form.get("csrf_token", "")):
            error = "요청이 만료되었습니다. 다시 시도해주세요."
            status = 400
        else:
            try:
                comment_id = queries.create_community_comment(
                    connection,
                    post_id=post_id,
                    author_id=session["user_id"],
                    author_username=session.get("username") or "",
                    content=content,
                )
            except ValueError as exc:
                error = str(exc)
                status = 400
            else:
                security_audit.log_event(
                    connection,
                    "COMMUNITY_COMMENT_CREATE",
                    "community_comment",
                    comment_id,
                    {"post_id": post_id, "content_length": len(content)},
                )
                connection.commit()
                return redirect(url_for("community_post_page", post_id=post_id) + "#comments")
        return render_template(
            "community_post.html",
            post=post,
            post_html=_render_community_markdown(post["content"]),
            comments=queries.list_community_comments(connection, post_id),
            can_comment=True,
            csrf_token=get_csrf_token(),
            comment_error=error,
            comment_content=content,
        ), status
    finally:
        connection.close()


@app.post("/board/<int:post_id>/recommend")
@login_required
def recommend_community_post_route(post_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        post = queries.get_community_post(connection, post_id)
        if not post or post["board_type"] == "diary":
            abort(404)
        try:
            recommended, count = queries.toggle_community_post_recommendation(
                connection, post_id, session["user_id"]
            )
        except ValueError:
            abort(404)
        security_audit.log_event(
            connection,
            "COMMUNITY_POST_RECOMMEND" if recommended else "COMMUNITY_POST_UNRECOMMEND",
            "community_post",
            post_id,
            {"recommendation_count": count},
        )
        connection.commit()
        return redirect(url_for("community_post_page", post_id=post_id) + "#post-actions")
    finally:
        connection.close()


@app.post("/board/<int:post_id>/comments/<int:comment_id>/delete")
@login_required
def delete_community_comment_route(post_id, comment_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        comment = queries.get_community_comment(connection, comment_id)
        if not comment or int(comment["post_id"]) != post_id:
            abort(404)
        is_owner = int(comment["author_id"]) == int(session["user_id"])
        if session.get("role") != "admin" and not is_owner:
            abort(403)
        queries.soft_delete_community_comment(connection, comment_id, session["user_id"])
        security_audit.log_event(
            connection,
            "COMMUNITY_COMMENT_DELETE",
            "community_comment",
            comment_id,
            {"post_id": post_id, "owner_delete": is_owner},
        )
        connection.commit()
        return redirect(url_for("community_post_page", post_id=post_id) + "#comments")
    finally:
        connection.close()


@app.post("/board/<int:post_id>/delete")
@login_required
def delete_community_post_route(post_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        post = queries.get_community_post(connection, post_id)
        if not post:
            abort(404)
        if post["board_type"] == "diary":
            abort(404)
        if not membership.can_board(
            connection, post["board_type"], "write",
            session.get("user_id"), session.get("role"),
        ):
            abort(403)
        is_owner = int(post["author_id"]) == int(session["user_id"])
        if session.get("role") != "admin" and not is_owner:
            abort(403)
        queries.soft_delete_community_post(connection, post_id, session["user_id"])
        security_audit.log_event(
            connection,
            "COMMUNITY_POST_DELETE",
            "community_post",
            post_id,
            {"board_type": post["board_type"], "owner_delete": is_owner},
        )
        connection.commit()
        return redirect(url_for(
            "notice_board_page"
            if post["board_type"] == "notice"
            else "community_board_page"
        ))
    finally:
        connection.close()


@app.post("/board/<int:post_id>/pin")
@admin_required
def set_community_post_pinned_route(post_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    is_pinned = request.form.get("is_pinned") == "1"
    connection = dashboard_db()
    try:
        try:
            queries.set_community_post_pinned(connection, post_id, is_pinned)
        except ValueError:
            abort(404)
        security_audit.log_event(
            connection,
            "COMMUNITY_POST_PIN" if is_pinned else "COMMUNITY_POST_UNPIN",
            "community_post",
            post_id,
        )
        connection.commit()
        return redirect(url_for("community_post_page", post_id=post_id))
    finally:
        connection.close()


# ============================================================
# 리서치
# ============================================================

def _library_context(connection, error=None):
    documents = queries.list_research_documents(connection)
    if g.locale == "en":
        documents = content_translation.apply_cached(connection, "research", documents)
    return {
        "documents": documents,
        "companies": queries.list_monitored_companies(connection),
        "selected_company": (request.args.get("company") or "").strip(),
        "csrf_token": get_csrf_token(),
        "error": error,
        "notice": (request.args.get("notice") or "").strip(),
    }


@app.route("/companies/reports", methods=["GET", "POST"])
def research_library_page():
    if request.method == "POST":
        if not session.get("user_id"):
            return redirect(
                url_for("auth.login", next=f"{request.script_root}{request.path}")
            )
        if not current_menu_permissions().get("research_library", False):
            abort(403)
    connection = dashboard_db()
    saved_file = None
    document_id = None
    try:
        if request.method == "POST":
            if not validate_csrf(request.form.get("csrf_token", "")):
                return render_template(
                    "library.html", **_library_context(connection, "요청이 만료되었습니다. 다시 시도해주세요.")
                ), 400

            allowed_companies = {
                item["name"] for item in queries.list_monitored_companies(connection)
            }
            submitted_company_names = request.form.getlist("company_names")
            # Older forms and clients used a single company_name field.
            if not submitted_company_names:
                submitted_company_names = [request.form.get("company_name", "")]
            company_names = list(dict.fromkeys(
                name.strip() for name in submitted_company_names
                if name.strip() in allowed_companies
            ))
            if not company_names:
                return render_template(
                    "library.html", **_library_context(connection, "분석 대상 회사를 하나 이상 선택해주세요.")
                ), 400
            company_name = company_names[0]

            uploaded = request.files.get("document")
            if not uploaded or not uploaded.filename:
                return render_template(
                    "library.html", **_library_context(connection, "업로드할 PDF를 선택해주세요.")
                ), 400

            extracted = document_library.save_and_extract(uploaded)
            saved_file = extracted["stored_filename"]
            duplicate = queries.find_research_document_by_hash(
                connection, company_name, extracted["sha256"]
            )
            if duplicate:
                document_library.remove_file(saved_file)
                saved_file = None
                return render_template(
                    "library.html",
                    **_library_context(
                        connection,
                        f"같은 파일이 이미 등록되어 있습니다: {duplicate['title']}",
                    ),
                ), 409

            submitted_title = (request.form.get("title") or "").strip()[:200]
            filename_title = extracted["original_filename"].rsplit(".", 1)[0]
            title = submitted_title or filename_title

            document_id = queries.create_research_document(
                connection,
                company_name=company_name,
                company_names=company_names,
                title=title,
                publisher=(request.form.get("publisher") or "").strip()[:120] or None,
                report_date=(request.form.get("report_date") or "").strip()[:10] or None,
                original_filename=extracted["original_filename"],
                stored_filename=extracted["stored_filename"],
                mime_type=extracted["mime_type"],
                file_size=extracted["file_size"],
                sha256=extracted["sha256"],
                page_count=extracted["page_count"],
                extracted_text=extracted["extracted_text"],
                extraction_status=extracted["extraction_status"],
                uploaded_by=session.get("username"),
            )
            security_audit.log_event(
                connection,
                "PDF_UPLOAD",
                "research_document",
                document_id,
                {
                    "company_names": company_names,
                    "filename": extracted["original_filename"],
                    "file_size": extracted["file_size"],
                    "sha256": extracted["sha256"],
                    "page_count": extracted["page_count"],
                },
            )
            connection.commit()
            saved_file = None
            document = queries.get_research_document(connection, document_id)
            analysis, analysis_error = ai_insights.analyze_research_document(connection, document)
            queries.update_research_document_analysis(
                connection, document_id, analysis=analysis, error_message=analysis_error
            )
            suggested_title = (
                str((analysis or {}).get("suggested_title") or "").strip()[:200]
            )
            if not submitted_title and suggested_title:
                queries.update_research_document_title(
                    connection,
                    document_id,
                    suggested_title,
                )
            notice = "업로드 및 AI 분석이 완료되었습니다." if analysis else (
                "자료는 저장했지만 AI 분석은 완료되지 않았습니다."
            )
            return redirect(url_for("research_library_page", notice=notice))

        selected = (request.args.get("company") or "").strip()
        context = _library_context(connection)
        if selected:
            context["documents"] = queries.list_research_documents(
                connection, company_name=selected
            )
        return render_template("library.html", **context)
    except document_library.DocumentUploadError as error:
        if saved_file:
            document_library.remove_file(saved_file)
        return render_template(
            "library.html", **_library_context(connection, str(error))
        ), 400
    except Exception:
        if document_id:
            document = queries.get_research_document(connection, document_id)
            if document:
                queries.delete_research_document(connection, document_id)
                try:
                    document_library.remove_file(document["stored_filename"])
                except OSError:
                    logger.exception("실패한 리서치 업로드 파일 정리 실패: %s", document_id)
        elif saved_file:
            document_library.remove_file(saved_file)
        logger.exception("리서치 업로드 처리 실패")
        return render_template(
            "library.html",
            **_library_context(connection, "자료 처리 중 오류가 발생했습니다."),
        ), 500
    finally:
        connection.close()


@app.route("/companies/reports/<int:document_id>/download")
def download_research_document(document_id):
    connection = dashboard_db()
    try:
        document = queries.get_research_document(connection, document_id)
        if not document:
            abort(404)
        path = document_library.document_path(document["stored_filename"])
        if not path.is_file():
            abort(404)
        security_audit.log_event(
            connection,
            "PDF_DOWNLOAD",
            "research_document",
            document_id,
            {
                "company_name": document.get("company_name"),
                "filename": document.get("original_filename"),
                "file_size": document.get("file_size"),
            },
        )
        connection.commit()
        return send_file(
            path,
            mimetype=document["mime_type"],
            as_attachment=True,
            download_name=document["original_filename"],
        )
    finally:
        connection.close()


@app.route("/companies/reports/<int:document_id>/reanalyze", methods=["POST"])
@login_required
def reanalyze_research_document(document_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        return redirect(url_for("research_library_page"))
    connection = dashboard_db()
    try:
        document = queries.get_research_document(connection, document_id)
        if not document:
            abort(404)
        analysis, error = ai_insights.analyze_research_document(
            connection, document, bypass_daily_limits=True
        )
        queries.update_research_document_analysis(
            connection, document_id, analysis=analysis, error_message=error
        )
        notice = "AI 재분석이 완료되었습니다." if analysis else f"재분석 실패: {error}"
        return redirect(url_for("research_library_page", notice=notice))
    finally:
        connection.close()


@app.route("/companies/reports/<int:document_id>/title", methods=["POST"])
@login_required
def update_research_document_title(document_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        return redirect(url_for("research_library_page"))
    connection = dashboard_db()
    try:
        document = queries.get_research_document(connection, document_id)
        if not document:
            abort(404)
        if request.form.get("title_mode") == "ai":
            title = (document.get("ai_suggested_title") or "").strip()
            if not title:
                return redirect(url_for(
                    "research_library_page",
                    notice="AI 추천 제목이 없습니다. 먼저 AI 재분석을 실행해주세요.",
                ))
        else:
            title = (request.form.get("title") or "").strip()
        if not title:
            return redirect(url_for(
                "research_library_page", notice="제목을 입력해주세요."
            ))
        queries.update_research_document_title(connection, document_id, title[:200])
        security_audit.log_event(
            connection,
            "RESEARCH_TITLE_UPDATE",
            "research_document",
            document_id,
            {
                "old_title": document.get("title"),
                "new_title": title[:200],
                "title_mode": request.form.get("title_mode") or "manual",
            },
        )
        connection.commit()
        return redirect(url_for(
            "research_library_page", notice="자료 제목을 수정했습니다."
        ))
    finally:
        connection.close()


@app.route("/companies/reports/<int:document_id>/delete", methods=["POST"])
@login_required
def delete_research_document(document_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        return redirect(url_for("research_library_page"))
    connection = dashboard_db()
    try:
        document = queries.get_research_document(connection, document_id)
        if not document:
            abort(404)
        queries.delete_research_document(connection, document_id)
        try:
            document_library.remove_file(document["stored_filename"])
        except OSError:
            logger.exception("삭제된 리서치 자료의 파일 정리 실패: %s", document_id)
        return redirect(url_for("research_library_page", notice="자료를 삭제했습니다."))
    finally:
        connection.close()


# ============================================================
# 통합 검색·이슈 타임라인
# ============================================================

@app.route("/search")
def unified_search_page():
    term = (request.args.get("q") or "").strip()[:100]
    try:
        days = max(7, min(int(request.args.get("days", 365)), 1095))
    except (TypeError, ValueError):
        days = 365

    all_source_labels = unified_search.SOURCE_LABELS
    if session.get("role") == "admin":
        allowed_sources = set(all_source_labels)
    elif session.get("user_id"):
        allowed_sources = set(all_source_labels) - {"insight", "performance"}
    else:
        allowed_sources = {"news", "disclosure", "law", "research"}
    source_labels = {
        source: label
        for source, label in all_source_labels.items()
        if source in allowed_sources
    }

    requested_sources = request.args.getlist("source")
    selected_sources = [
        source for source in requested_sources if source in allowed_sources
    ]
    if not selected_sources:
        selected_sources = list(source_labels)

    connection = dashboard_db()
    try:
        # SQL LIKE의 '%'와 '_'를 검색어로 직접 허용하면 빈 문자열에 가까운
        # 전체 열람 쿼리가 된다. 사용자 입력 경계에서 막아 자료 열거를 방지한다.
        if "%" in term or "_" in term:
            results = []
        else:
            results = unified_search.search(
                connection,
                term,
                days=days,
                sources=selected_sources,
                limit=250,
            )
        if session.get("role") != "admin":
            username = session.get("username") or ""
            results = [
                item for item in results
                if item["source"] != "action" or item.get("reported_by") == username
            ]
        counts = {
            source: sum(item["source"] == source for item in results)
            for source in source_labels
        }
        return render_template(
            "search.html",
            term=term,
            days=days,
            results=results,
            counts=counts,
            source_labels=source_labels,
            selected_sources=set(selected_sources),
        )
    finally:
        connection.close()


@app.route("/healthz")
def healthz():
    return {"status": "ok"}


@app.route("/<path:unknown_path>")
def not_found_page(unknown_path):
    # PythonAnywhere의 기본 404 응답 대신 항상 대시보드 디자인을 사용한다.
    return _render_error_page(404)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)

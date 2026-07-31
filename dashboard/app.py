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
import time
from datetime import datetime, timedelta
from urllib.parse import quote, urlsplit
from xml.etree.ElementTree import Element, SubElement, tostring

from flask import (
    Flask, abort, flash, g, jsonify, redirect, render_template, request, send_file,
    session, url_for,
)

import config
from auth import (
    MENU_PERMISSIONS,
    auth_bp,
    current_menu_permissions,
    get_csrf_token,
    login_required,
    validate_csrf,
)
from dashboard_db import queries
from extensions import dashboard_db
from services import (
    ai_insights,
    casino_industry,
    casino_statistics,
    company_intelligence,
    document_library,
    economic_data,
    market_data,
    news_reader,
    official_document_manager,
    performance_parser,
    salary_data,
    security_audit,
    telegram_alert,
    unified_search,
)
from official_docs import official_docs_bp
from tips import tips_bp
from localization import (
    LocalePrefixMiddleware,
    alternate_paths,
    load_catalog,
    locale_from_environ,
    meta_for,
    translate_html,
    translate_structure,
    translate_text,
)
from utils import display_y_drive_path, escape_html, setup_logger, today_kst_str

logger = setup_logger("dashboard_app")

CANONICAL_URL = config.DASHBOARD_PUBLIC_URL.rstrip("/")
_CANONICAL_PARTS = urlsplit(CANONICAL_URL)
CANONICAL_SCHEME = (_CANONICAL_PARTS.scheme or "https").lower()
CANONICAL_HOST = (_CANONICAL_PARTS.netloc or "").split(":", 1)[0].lower()
SEO_IMAGE_URL = f"{CANONICAL_URL}/static/img/casino-in-logo.png"
INDEXABLE_ENDPOINTS = {
    "public_home",
    "market_trend_page",
    "related_news_page",
    "tourism_trend_page",
    "economic_trend_page",
    "holiday_calendar_page",
    "salary_trend_page",
    "recruitment_page",
    "casino_industry_page",
    "casino_visitors_page",
    "casino_revenue_page",
    "casino_fund_page",
    "disclosures_page",
    "laws_page",
    "companies_page",
    "research_library_page",
    "credits_page",
    "tips.list_page",
    "tips.sites_page",
    "tips.detail_page",
}
NOINDEX_ENDPOINTS = {
    "auth.login",
    "auth.register",
    "auth.user_management",
    "dashboard_home",
    "paradian_portal_page",
    "performance_page",
    "sitemap_page",
    "unified_search_page",
    "action_items_page",
    "action_item_detail",
    "not_found_page",
}
SITEMAP_STATIC_ENDPOINTS = {
    "public_home": {"changefreq": "daily", "priority": "1.0"},
    "casino_industry_page": {"changefreq": "monthly", "priority": "0.95"},
    "related_news_page": {"changefreq": "hourly", "priority": "0.9"},
    "market_trend_page": {"changefreq": "daily", "priority": "0.85"},
    "tourism_trend_page": {"changefreq": "monthly", "priority": "0.85"},
    "economic_trend_page": {"changefreq": "daily", "priority": "0.85"},
    "holiday_calendar_page": {"changefreq": "monthly", "priority": "0.7"},
    "salary_trend_page": {"changefreq": "daily", "priority": "0.7"},
    "recruitment_page": {"changefreq": "daily", "priority": "0.75"},
    "disclosures_page": {"changefreq": "daily", "priority": "0.9"},
    "laws_page": {"changefreq": "daily", "priority": "0.9"},
    "companies_page": {"changefreq": "daily", "priority": "0.85"},
    "research_library_page": {"changefreq": "weekly", "priority": "0.8"},
    "tips.list_page": {"changefreq": "weekly", "priority": "0.8"},
    "tips.sites_page": {"changefreq": "weekly", "priority": "0.65"},
    "credits_page": {"changefreq": "weekly", "priority": "0.5"},
}
SEO_PAGE_COPY = {
    "ko": {
        "public_home": (
            "Casino IN | 카지노 산업 정보와 인사이트",
            "국내외 카지노 기업, 관광객, 환율, 공시, 시장 동향과 산업 데이터를 한곳에서 확인하는 카지노 산업 인텔리전스 플랫폼입니다.",
        ),
        "casino_industry_page": (
            "카지노업 현황 | Casino IN",
            "국내 외국인전용 카지노 사업장 현황, 지역 분포, 매출과 이용객 데이터를 한 화면에서 확인합니다.",
        ),
        "related_news_page": (
            "카지노 산업 뉴스 | Casino IN",
            "국내외 카지노·관광 산업 뉴스와 AI 관점 분석을 한곳에서 확인합니다.",
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
        "disclosures_page": (
            "카지노 기업 공시정보 | Casino IN",
            "관심 카지노 기업의 DART 공시, 제출인, AI 요약을 한곳에서 확인합니다.",
        ),
        "laws_page": (
            "카지노 법률·규제 모니터링 | Casino IN",
            "카지노 영업준칙, 관광진흥법, 정부입법예고와 국회 의안 동향을 추적합니다.",
        ),
        "companies_page": (
            "국내외 카지노 기업 분석 | Casino IN",
            "파라다이스, GKL, 강원랜드, 롯데관광개발 등 주요 기업 정보를 비교 분석합니다.",
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
            "출처 및 저작권 | Casino IN",
            "Casino IN에서 사용하는 데이터 출처, 업데이트 주기, 최종 확인 시각을 안내합니다.",
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
            "Casino Industry Overview | Casino IN",
            "Explore Korean foreigner-only casino properties, locations, revenue, and visitor data in one place.",
        ),
        "related_news_page": (
            "Casino Industry News | Casino IN",
            "Follow casino and travel-industry news with AI commentary and issue tracking.",
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
        "disclosures_page": (
            "Casino Company Disclosures | Casino IN",
            "Monitor DART filings, submitters, and AI summaries for tracked casino companies.",
        ),
        "laws_page": (
            "Casino Regulation Monitor | Casino IN",
            "Track casino operating rules, tourism law updates, government notices, and National Assembly bills.",
        ),
        "companies_page": (
            "Casino Company Analysis | Casino IN",
            "Compare Paradise, GKL, Kangwon Land, Lotte Tour Development, and other casino-linked companies.",
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
            "Sources and Copyright | Casino IN",
            "See the data sources, refresh cadence, and latest verification times used across Casino IN.",
        ),
        "sitemap_page": (
            "Sitemap | Casino IN",
            "Browse the public page structure of Casino IN.",
        ),
    },
}
_STRIP_TAGS_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY or "dev-only-insecure-key-set-FLASK_SECRET_KEY"
app.permanent_session_lifetime = timedelta(hours=config.SESSION_ABSOLUTE_HOURS)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=True,
    MAX_CONTENT_LENGTH=max(
        config.RESEARCH_MAX_FILE_BYTES,
        config.OFFICIAL_DOC_MAX_UPLOAD_MB * 1024 * 1024,
        config.TIPS_MAX_ATTACHMENT_BYTES,
    ) + (512 * 1024),
)
app.wsgi_app = LocalePrefixMiddleware(app.wsgi_app)

if not config.FLASK_SECRET_KEY:
    logger.warning("FLASK_SECRET_KEY가 설정되지 않아 임시 키를 사용합니다. 재시작 시 세션이 모두 만료됩니다.")

app.register_blueprint(auth_bp)
app.register_blueprint(official_docs_bp)
app.register_blueprint(tips_bp)

ENDPOINT_PERMISSIONS = {
    "action_items_page": "bug_reports",
    "action_item_detail": "bug_reports",
    "add_action_item_comment": "bug_reports",
    "edit_action_item_comment": "bug_reports",
    "delete_action_item_comment": "bug_reports",
    "update_action_item_route": "bug_reports",
    "delete_action_item_route": "bug_reports",
    "disclosures_page": "disclosures",
    "laws_page": "laws",
    "companies_page": "companies",
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
    "tourism_trend_page",
    "economic_trend_page",
    "holiday_calendar_page",
    "salary_trend_page",
    "recruitment_page",
    "casino_industry_page",
    "casino_visitors_page",
    "casino_revenue_page",
    "casino_fund_page",
    "disclosures_page",
    "laws_page",
    "companies_page",
    "research_library_page",
    "download_research_document",
    "unified_search_page",
    "credits_page",
    "tips.list_page",
    "tips.sites_page",
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
        return today_kst_str()
    return str(value)[:10]


def _alternate_absolute_urls(path):
    localized_paths = alternate_paths(path)
    return {
        locale: f"{CANONICAL_URL}{localized_path}"
        for locale, localized_path in localized_paths.items()
    }


def _neutral_url_for(endpoint, **values):
    path = url_for(endpoint, **values)
    if path == "/en":
        return "/"
    if path.startswith("/en/"):
        return path[3:]
    return path


def _seo_defaults():
    locale = getattr(g, "locale", "ko")
    endpoint = request.endpoint or ""
    seo_paths = alternate_paths(request.path)
    canonical_path = seo_paths[locale]
    localized_copy = SEO_PAGE_COPY.get(locale, {})
    fallback_title = (
        "Casino IN | 카지노 산업 정보와 인사이트"
        if locale == "ko"
        else "Casino IN | Casino Industry Information and Insights"
    )
    fallback_description = (
        "국내외 카지노 산업 뉴스, 기업정보, 공시, 관광객, 환율, 시장 데이터와 인사이트를 제공하는 정보 플랫폼입니다."
        if locale == "ko"
        else "An information platform covering casino-industry news, company data, disclosures, tourism, FX, and market intelligence."
    )
    title, description = localized_copy.get(
        endpoint,
        (fallback_title, fallback_description),
    )
    robots = "index,follow" if endpoint in INDEXABLE_ENDPOINTS else "noindex,nofollow"
    structured_data = []
    if endpoint == "public_home":
        website = {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": "Casino IN",
            "url": f"{CANONICAL_URL}/",
            "description": description,
            "inLanguage": "ko-KR" if locale == "ko" else "en-US",
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
        webpage = {
            "@context": "https://schema.org",
            "@type": "WebPage",
            "name": title,
            "url": f"{CANONICAL_URL}{canonical_path}",
            "description": description,
            "isPartOf": {"@type": "WebSite", "name": "Casino IN", "url": f"{CANONICAL_URL}/"},
        }
        structured_data = [website, organization, webpage]
    return {
        "seo_title": title,
        "seo_description": description,
        "seo_robots": robots,
        "seo_canonical_url": f"{CANONICAL_URL}{canonical_path}",
        "seo_hreflang_urls": {
            "ko": f"{CANONICAL_URL}{seo_paths['ko']}",
            "en": f"{CANONICAL_URL}{seo_paths['en']}",
            "x-default": f"{CANONICAL_URL}{seo_paths['ko']}",
        },
        "seo_og_title": title,
        "seo_og_description": description,
        "seo_og_type": "website",
        "seo_og_url": f"{CANONICAL_URL}{canonical_path}",
        "seo_image_url": SEO_IMAGE_URL,
        "seo_image_alt": "Casino IN logo",
        "seo_twitter_card": "summary_large_image",
        "seo_json_ld": structured_data,
    }


@app.before_request
def establish_request_security():
    g.locale = locale_from_environ(request.environ)
    host = request.host.split(":", 1)[0].lower()
    if request.method in {"GET", "HEAD"} and request.endpoint != "healthz":
        current_scheme = _request_scheme()
        if host in config.TRUSTED_HOSTS and (
            host != CANONICAL_HOST or current_scheme != CANONICAL_SCHEME
        ):
            target = f"{CANONICAL_SCHEME}://{CANONICAL_HOST}{request.full_path}"
            if target.endswith("?"):
                target = target[:-1]
            return redirect(target, code=301)
    if not app.testing and host not in config.TRUSTED_HOSTS:
        abort(400)
    g.csp_nonce = secrets.token_urlsafe(18)


@app.after_request
def apply_security_headers(response):
    nonce = getattr(g, "csp_nonce", "")
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "; ".join((
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}' https://www.googletagmanager.com",
        "script-src-attr 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "font-src 'self' https://cdn.jsdelivr.net data:",
        "img-src 'self' data: https://www.google-analytics.com https://www.googletagmanager.com",
        "connect-src 'self' https://www.google-analytics.com https://analytics.google.com "
        "https://region1.google-analytics.com https://www.googletagmanager.com",
        "frame-src https://www.googletagmanager.com",
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
    return response


@app.after_request
def localize_response(response):
    """Translate rendered UI while leaving stored Korean source data untouched."""

    locale = getattr(g, "locale", "ko")
    response.headers["Content-Language"] = locale
    if locale != "en" or response.direct_passthrough:
        return response

    content_type = response.headers.get("Content-Type", "")
    if content_type.startswith("text/html"):
        response.set_data(translate_html(response.get_data(as_text=True), locale))
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
def log_authenticated_activity(response):
    """로그인 사용자의 화면 조회와 작업 실행을 관리자 감사 로그에 남긴다."""
    if (
        session.get("user_id")
        and request.endpoint
        and request.endpoint not in {"static", "healthz"}
        and request.endpoint not in {
            "auth.login", "auth.test_login", "auth.logout", "auth.register"
        }
    ):
        connection = dashboard_db()
        try:
            security_audit.log_event(
                connection,
                "PAGE_VIEW" if request.method == "GET" else "USER_ACTION",
                "endpoint",
                request.endpoint,
                {
                    "method": request.method,
                    "path": f"{request.script_root}{request.path}"[:500],
                    "locale": getattr(g, "locale", "ko"),
                    "status_code": response.status_code,
                },
                success=response.status_code < 400,
            )
            # 활동 로그는 180일만 보관해 DB가 계속 커지는 것을 방지한다.
            connection.execute(
                "DELETE FROM security_audit_log WHERE created_at < datetime('now', '-180 days')"
            )
            connection.commit()
        except Exception:
            logger.exception("사용자 활동 로그 저장 실패")
        finally:
            connection.close()
    return response


@app.before_request
def enforce_menu_permission():
    if not session.get("user_id"):
        return None
    if request.endpoint == "performance_page" and session.get("username") != "admin":
        abort(403)
    if request.method in {"GET", "HEAD"} and request.endpoint in PUBLIC_READ_ENDPOINTS:
        return None
    # 공문·자료관리는 별도 세부 권한 없이 로그인 사용자에게 허용한다.
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
    if not role and session.get("user_id"):
        connection = dashboard_db()
        try:
            row = connection.execute(
                "SELECT role FROM dashboard_users WHERE id=?", (session["user_id"],)
            ).fetchone()
            role = (row["role"] if row else None) or "user"
            session["role"] = role
        finally:
            connection.close()
    endpoint_menu_names = {
        "public_home": "시작 화면",
        "dashboard_home": "홈",
        "action_items_page": "의견",
        "action_item_detail": "의견",
        "performance_page": "데이터",
        "paradian_portal_page": "파라디안 전용",
        "related_news_page": "관련 뉴스",
        "market_trend_page": "주가 정보",
        "tourism_trend_page": "관광객 추이",
        "economic_trend_page": "유가정보·환율",
        "holiday_calendar_page": "나라별 연휴",
        "salary_trend_page": "연봉",
        "recruitment_page": "채용",
        "casino_industry_page": "카지노업 현황",
        "casino_visitors_page": "연도별 카지노 이용객",
        "casino_revenue_page": "연도별 카지노 매출액 비율",
        "casino_fund_page": "기금 부과 현황",
        "disclosures_page": "공시·재무",
        "laws_page": "법률·규제",
        "companies_page": "기업 360°",
        "research_library_page": "리서치",
        "download_research_document": "리서치",
        "reanalyze_research_document": "리서치",
        "update_research_document_title": "리서치",
        "delete_research_document": "리서치",
        "unified_search_page": "통합검색",
        "sitemap_page": "사이트맵",
        "credits_page": "출처 및 저작권",
        "auth.login": "로그인",
        "auth.register": "가입 신청",
        "auth.user_management": "계정관리",
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
    seo_paths = alternate_paths(request.path)
    switch_paths = alternate_paths(
        request.path, request.query_string.decode("utf-8", errors="ignore")
    )
    target_locale = "ko" if locale == "en" else "en"
    catalog = load_catalog()
    seo_defaults = _seo_defaults()
    return {
        "current_username": session.get("username"),
        "now_str": today_kst_str(),
        "current_user_role": role or "anonymous",
        "menu_permissions": current_menu_permissions(),
        "csp_nonce": getattr(g, "csp_nonce", ""),
        "global_csrf_token": get_csrf_token(),
        "current_menu_name": current_menu_name,
        "display_y_drive_path": display_y_drive_path,
        "current_locale": locale,
        "locale_prefix": "/en" if locale == "en" else "",
        "locale_switch_url": switch_paths[target_locale],
        "locale_switch_label": target_locale.upper(),
        "locale_urls": switch_paths,
        "canonical_url": seo_defaults["seo_canonical_url"],
        "hreflang_urls": seo_defaults["seo_hreflang_urls"],
        "localized_meta": meta_for(locale),
        "i18n_catalog": catalog,
        "t": lambda value: translate_text(value, locale),
        **seo_defaults,
    }


def _site_map_links():
    """현재 로그인 상태와 메뉴 권한에 맞는 사이트맵 링크를 반환한다."""
    links = [
        {"label": "시작 화면", "description": "공개 메뉴와 로그인 안내", "endpoint": "public_home"},
        {"label": "출처 및 저작권", "description": "데이터 출처, 업데이트 주기, 최종 확인 시간", "endpoint": "credits_page"},
    ]
    links.append(
        {"label": "데이터", "description": "뉴스·주가·카지노업·관광객·경제지표·연휴·연봉·채용", "endpoint": "market_trend_page"}
    )
    menu_links = (
        ("disclosures", "공시·재무", "DART 공시 및 재무정보", "disclosures_page"),
        ("laws", "법률·규제", "카지노 관련 법령 모니터링", "laws_page"),
        ("companies", "기업 360°", "회사별 통합 기업분석", "companies_page"),
        ("research_library", "리서치", "기업·산업 리포트 분석", "research_library_page"),
        ("unified_search", "통합검색", "뉴스·공시·법령·자료 검색", "unified_search_page"),
        ("tips", "자료실", "업무 노하우와 자동화 자료", "tips.list_page"),
        ("bug_reports", "의견", "질문·버그·기능 제안·일반 의견", "action_items_page"),
    )
    links.extend(
        {
            "label": label,
            "description": description,
            "endpoint": endpoint,
            "locked": False,
        }
        for permission, label, description, endpoint in menu_links
    )
    if not session.get("user_id"):
        links.extend([
            {"label": "파라디안 전용", "description": "로그인 후 공문·자료관리 이용", "endpoint": "auth.login", "locked": True},
            {"label": "로그인", "description": "대시보드 계정으로 접속", "endpoint": "auth.login"},
            {"label": "가입 신청", "description": "새 계정 승인 요청", "endpoint": "auth.register"},
        ])
        return links
    links.extend([
        {"label": "파라디안 전용", "description": "공문·자료관리 및 관리자 경영 실적", "endpoint": "paradian_portal_page"},
        {"label": "공문·자료관리", "description": "접수·처리·Y디스크 보관", "endpoint": "official_docs.dashboard"},
    ])
    if session.get("username") == "admin":
        links.append(
            {"label": "경영 실적", "description": "내부 경영 실적 현황", "endpoint": "performance_page"}
        )
    if session.get("role") == "admin":
        links.append({
            "label": "계정·권한관리",
            "description": "계정, 세션, 로그인·활동 로그",
            "endpoint": "auth.user_management",
        })
    return links


@app.route("/sitemap")
def sitemap_page():
    return render_template("sitemap.html", site_map_links=_site_map_links())


def _sitemap_url_entry(path, lastmod, changefreq, priority):
    urls = _alternate_absolute_urls(path)
    entries = []
    for locale_path in (urls["ko"], urls["en"]):
        entries.append({
            "loc": locale_path,
            "lastmod": _date_only(lastmod),
            "changefreq": changefreq,
            "priority": priority,
        })
    return entries


def _build_sitemap_entries(connection):
    entries = []
    static_lastmods = {
        "public_home": max(
            filter(
                None,
                (
                    news_reader.last_updated_at(),
                    _max_timestamp(connection, "law_updates", "fetched_at"),
                    _max_timestamp(connection, "dart_disclosures", "fetched_at"),
                ),
            ),
            default=today_kst_str(),
        ),
        "casino_industry_page": today_kst_str(),
        "related_news_page": news_reader.last_updated_at() or today_kst_str(),
        "market_trend_page": _max_timestamp(connection, "market_quotes", "fetched_at"),
        "tourism_trend_page": _max_timestamp(connection, "tourism_visitor_stats", "fetched_at"),
        "economic_trend_page": _max_timestamp(connection, "economic_series", "fetched_at"),
        "holiday_calendar_page": today_kst_str(),
        "salary_trend_page": _max_timestamp(connection, "salary_snapshots", "fetched_at"),
        "recruitment_page": _max_timestamp(connection, "recruitment_jobs", "last_seen_at"),
        "disclosures_page": _max_timestamp(connection, "dart_disclosures", "fetched_at"),
        "laws_page": _max_timestamp(connection, "law_updates", "fetched_at"),
        "companies_page": max(
            filter(
                None,
                (
                    _max_timestamp(connection, "company_research_profiles", "updated_at"),
                    _max_timestamp(connection, "research_documents", "updated_at"),
                ),
            ),
            default=today_kst_str(),
        ),
        "research_library_page": _max_timestamp(connection, "research_documents", "updated_at"),
        "tips.list_page": _max_timestamp(connection, "tips_articles", "updated_at", "is_deleted=0 AND draft=0"),
        "tips.sites_page": _max_timestamp(connection, "related_sites", "updated_at", "is_deleted=0 AND is_public=1"),
        "credits_page": max(
            filter(
                None,
                (
                    _max_timestamp(connection, "dashboard_analysis_runs", "finished_at"),
                    _max_timestamp(connection, "tips_articles", "updated_at", "is_deleted=0 AND draft=0"),
                ),
            ),
            default=today_kst_str(),
        ),
    }
    for endpoint, meta in SITEMAP_STATIC_ENDPOINTS.items():
        entries.extend(
            _sitemap_url_entry(
                _neutral_url_for(endpoint),
                static_lastmods.get(endpoint) or today_kst_str(),
                meta["changefreq"],
                meta["priority"],
            )
        )

    tip_rows = connection.execute(
        """
        SELECT slug, updated_at, published_date, title, summary, body
        FROM tips_articles
        WHERE is_deleted=0 AND draft=0
        ORDER BY published_date DESC, created_at DESC
        """
    ).fetchall()
    for row in tip_rows:
        entries.extend(
            _sitemap_url_entry(
                _neutral_url_for("tips.detail_page", slug=row["slug"]),
                row["updated_at"] or row["published_date"],
                "monthly",
                "0.7",
            )
        )
    return entries


@app.route("/robots.txt")
def robots_txt():
    lines = [
        "User-agent: *",
        "Allow: /",
        "",
        "Disallow: /admin/",
        "Disallow: /login",
        "Disallow: /logout",
        "Disallow: /register",
        "Disallow: /api/",
        "Disallow: /official-docs/",
        "Disallow: /paradian",
        "Disallow: /bug-reports",
        "Disallow: /action-items",
        "Disallow: /en/login",
        "Disallow: /en/logout",
        "Disallow: /en/register",
        "Disallow: /en/api/",
        "Disallow: /en/official-docs/",
        "Disallow: /en/paradian",
        "Disallow: /en/bug-reports",
        "Disallow: /en/action-items",
        "",
        f"Sitemap: {CANONICAL_URL}/sitemap.xml",
    ]
    return app.response_class("\n".join(lines), mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    connection = dashboard_db()
    try:
        entries = _build_sitemap_entries(connection)
    finally:
        connection.close()
    urlset = Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    for entry in entries:
        url_node = SubElement(urlset, "url")
        SubElement(url_node, "loc").text = entry["loc"]
        SubElement(url_node, "lastmod").text = entry["lastmod"]
        SubElement(url_node, "changefreq").text = entry["changefreq"]
        SubElement(url_node, "priority").text = entry["priority"]
    xml = tostring(urlset, encoding="utf-8", xml_declaration=True)
    return app.response_class(xml, mimetype="application/xml")


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


def _credits_rows(connection):
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
        "데이터",
        "카지노 관련 뉴스",
        "news_history.db / AI 이슈 요약 아카이브",
        "",
        "외부 수집 DB 반영 주기에 따름",
        checked_at=news_updated_at,
        changed_at=news_updated_at,
        notes="대시보드는 읽기 전용으로 연동하며, 원본 뉴스 DB의 최종 수집 시각을 표시합니다.",
    )

    dart_freshness = queries.get_data_freshness(
        connection, "dart_disclosures", "dart_sync", "fetched_at"
    )
    push(
        "공시·재무",
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
        "데이터",
        "국내 주가·지수",
        "공공데이터포털 API",
        "https://www.data.go.kr/",
        "배치 + 화면 진입 시 자동 확인",
        checked_at=market_freshness.get("domestic_checked_at"),
        changed_at=market_freshness.get("domestic_checked_at"),
        notes="국내 4개 카지노 기업과 KOSPI를 자동 확인하며, 오래된 시세는 페이지 진입 시 즉시 재조회합니다.",
    )
    push(
        "데이터",
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
        "데이터",
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
        "데이터",
        "유가정보",
        "한국석유공사 Opinet",
        "https://www.opinet.co.kr/",
        "배치 + 화면 진입 시 자동 갱신",
        checked_at=economic_freshness.get("oil_checked_at"),
        changed_at=economic_freshness.get("oil_changed_at"),
        notes="보통휘발유·경유·부탄 평균가를 자동 갱신하며, 오래된 데이터는 화면 진입 시 재수집합니다.",
    )
    push(
        "데이터",
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
        "데이터",
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
        "데이터",
        "채용",
        "잡코리아 / 사람인 / 인크루트",
        "https://www.jobkorea.co.kr/",
        "매일 정기 동기화",
        checked_at=(recruitment_sync or {}).get("finished_at"),
        changed_at=_max_timestamp(connection, "recruitment_jobs", "last_seen_at"),
        notes="AI가 고용형태, 처우, 확인 필요 사항을 카드형으로 요약합니다.",
    )

    push(
        "리서치",
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
        "파라디안 전용",
        "공문·자료관리",
        "내부 접수 자료 / Y드라이브 연계",
        "",
        "등록 즉시 반영",
        checked_at=_max_timestamp(connection, "official_documents", "updated_at", "is_active=1"),
        changed_at=_max_timestamp(connection, "official_documents", "updated_at", "is_active=1"),
        notes="삭제 자료는 즉시 물리 삭제하지 않고 보존 정책에 따라 관리합니다.",
    )

    push(
        "파라디안 전용",
        "경영 실적",
        "텔레그램 성과 메시지 수집",
        "",
        "메시지 수신 / 수집 작업 기준",
        checked_at=_max_timestamp(connection, "performance_reports", "created_at"),
        changed_at=_max_timestamp(connection, "performance_reports", "report_date"),
        notes="성공적으로 수집된 최신 보고 메시지 기준 시각을 표시합니다.",
    )

    return rows


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
    return redirect(url_for("public_home"), code=302)


@app.route("/paradian")
@login_required
def paradian_portal_page():
    return render_template("paradian_portal.html")


# ============================================================
# Action Items
# ============================================================

def can_access_action_item(item):
    return bool(
        item
        and (
            session.get("role") == "admin"
            or (
                session.get("username")
                and item.get("reported_by") == session.get("username")
            )
        )
    )


@app.route("/action-items", methods=["GET", "POST"])
@app.route("/bug-reports", methods=["GET", "POST"])
def action_items_page():
    if request.method == "POST" and not session.get("user_id"):
        return redirect(
            url_for("auth.login", next=f"{request.script_root}{request.path}")
        )
    connection = dashboard_db()
    try:
        is_admin = session.get("role") == "admin"
        username = session.get("username") or ""

        def visible_items(status=None):
            if not username:
                return []
            return queries.list_action_items(
                connection,
                status=status,
                reported_by=None if is_admin else username,
            )

        if request.method == "POST":
            if not validate_csrf(request.form.get("csrf_token", "")):
                return render_template("action_items.html", error="요청이 만료되었습니다. 다시 시도해주세요.",
                                        items=visible_items(), csrf_token=get_csrf_token(),
                                        is_admin=is_admin), 400

            title = (request.form.get("title") or "").strip()
            if not title:
                return render_template("action_items.html", error="제목을 입력해주세요.",
                                        items=visible_items(), csrf_token=get_csrf_token(),
                                        is_admin=is_admin), 400

            description = (request.form.get("description") or "").strip()
            priority = request.form.get("priority") or "보통"
            bug_page = (request.form.get("bug_page") or "").strip()
            environment = (request.form.get("environment") or "").strip()
            feedback_type = request.form.get("feedback_type") or "일반 의견"
            if feedback_type not in {"질문", "버그 제보", "기능 제안", "일반 의견"}:
                feedback_type = "일반 의견"
            reporter = username
            item_id = queries.create_action_item(
                connection,
                title=title,
                description=description,
                owner=(request.form.get("owner") or "").strip() or None,
                priority=priority,
                source_type="bug_report",
                status="접수",
                reported_by=reporter,
                bug_page=bug_page,
                environment=environment,
                feedback_type=feedback_type,
            )
            bug_url = url_for(
                "action_item_detail", item_id=item_id, _external=True
            )
            alert_lines = [
                "💬 <b>새 의견</b>",
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
                    connection, "bug_report_alert", "telegram_send_failed",
                    f"버그 #{item_id} Telegram 알림 전송 실패",
                )
            return redirect(url_for("action_items_page"))

        status_filter = request.args.get("status") or None
        items = visible_items(status_filter)
        return render_template("action_items.html", items=items, csrf_token=get_csrf_token(),
                                status_filter=status_filter, is_admin=is_admin)
    finally:
        connection.close()


@app.get("/bug-reports/<int:item_id>")
@login_required
def action_item_detail(item_id):
    connection = dashboard_db()
    try:
        item = queries.get_action_item(connection, item_id)
        if not item:
            abort(404)
        if not can_access_action_item(item):
            abort(403)
        comments = queries.list_action_item_comments(connection, item_id)
        return render_template(
            "action_item_detail.html",
            item=item,
            comments=comments,
            csrf_token=get_csrf_token(),
            is_admin=session.get("role") == "admin",
        )
    finally:
        connection.close()


@app.post("/bug-reports/<int:item_id>/comments")
@login_required
def add_action_item_comment(item_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        item = queries.get_action_item(connection, item_id)
        if not item:
            abort(404)
        if not can_access_action_item(item):
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


@app.post("/bug-reports/<int:item_id>/comments/<int:comment_id>/edit")
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
        if not can_access_action_item(item):
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


@app.post("/bug-reports/<int:item_id>/comments/<int:comment_id>/delete")
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
        if not can_access_action_item(item):
            abort(403)
        if comment["author_id"] != session.get("user_id") and session.get("role") != "admin":
            abort(403)
        queries.delete_action_item_comment(connection, comment_id, session["user_id"])
        flash("댓글을 삭제했습니다.", "success")
    finally:
        connection.close()
    return redirect(url_for("action_item_detail", item_id=item_id) + "#comments")


@app.route("/action-items/<int:item_id>/update", methods=["POST"])
@login_required
def update_action_item_route(item_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        return redirect(url_for("action_items_page"))

    connection = dashboard_db()
    try:
        item = queries.get_action_item(connection, item_id)
        if not item:
            abort(404)
        is_admin = session.get("role") == "admin"
        if not can_access_action_item(item):
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
            fields["feedback_type"] = "일반 의견"
        if "title" in fields and not fields["title"]:
            abort(400)
        if fields:
            queries.update_action_item(connection, item_id, **fields)
        if is_admin and request.form.get("approve") == "1":
            queries.approve_action_item(connection, item_id)
    finally:
        connection.close()
    return redirect(
        request.form.get("next")
        if request.form.get("next", "").startswith("/bug-reports/")
        else url_for("action_items_page")
    )


@app.route("/action-items/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_action_item_route(item_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        return redirect(url_for("action_items_page"))
    connection = dashboard_db()
    try:
        item = queries.get_action_item(connection, item_id)
        if not item:
            abort(404)
        if session.get("role") != "admin":
            abort(403)
        queries.delete_action_item(connection, item_id)
    finally:
        connection.close()
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


@app.route("/performance")
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


@app.route("/performance/tourism")
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


@app.route("/performance/casino-industry")
def casino_industry_page():
    return render_template(
        "casino_industry.html",
        casino_industry=casino_industry.build_dashboard(
            request.args.get("region", "").strip()
        ),
    )


@app.route("/performance/casino-industry/visitors")
def casino_visitors_page():
    return render_template(
        "casino_history.html",
        mode="visitors",
        page_title="연도별 카지노 이용객",
        page_description="외래 방한객과 외국인전용 카지노 이용객의 장기 추이·점유율·증감률을 확인합니다.",
        statistics=casino_statistics.build_visitors(),
    )


@app.route("/performance/casino-industry/revenue")
def casino_revenue_page():
    return render_template(
        "casino_history.html",
        mode="revenue",
        page_title="연도별 카지노 매출액 비율",
        page_description="관광 외화수입 대비 카지노 외화수입의 장기 추이와 점유율을 확인합니다.",
        statistics=casino_statistics.build_revenue(),
    )


@app.route("/performance/casino-industry/fund")
def casino_fund_page():
    return render_template(
        "casino_fund.html",
        fund=casino_statistics.build_fund(),
    )


@app.route("/performance/markets")
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


@app.route("/performance/news")
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
    articles = news_reader.list_articles(
        days=days,
        term=term,
        category=category,
        impact_direction=impact,
        important_only=important_only,
    )
    connection = dashboard_db()
    try:
        executive_insights = queries.list_recent_executive_insights(
            connection, days=days, limit=50
        )
    finally:
        connection.close()
    return render_template(
        "related_news.html",
        articles=articles,
        categories=news_reader.list_categories(),
        news_stats=news_reader.article_stats(days),
        executive_insights=executive_insights,
        news_updated_at=news_reader.last_updated_at(),
        selected_days=days,
        selected_term=term,
        selected_category=category,
        selected_impact=impact,
        important_only=important_only,
    )


@app.route("/performance/economy")
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


@app.route("/performance/holidays")
def holiday_calendar_page():
    from services import holiday_calendar
    return render_template(
        "holiday_calendar.html",
        holiday_calendar=holiday_calendar.build_calendar(request.args.get("year", 2026, type=int)),
    )


@app.route("/performance/salaries")
def salary_trend_page():
    connection = dashboard_db()
    try:
        items = queries.list_salary_dashboard(connection)
        latest_run = queries.get_latest_completed_run(connection, "salary_sync")
        return render_template(
            "salary_trend.html",
            salary_items=items,
            salary_checked_at=latest_run.get("finished_at") if latest_run else None,
            salary_check_status=latest_run.get("status") if latest_run else None,
        )
    finally:
        connection.close()


@app.route("/performance/recruitment")
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

@app.route("/disclosures")
def disclosures_page():
    connection = dashboard_db()
    try:
        days = int(request.args.get("days", 7))
        disclosures = queries.list_recent_disclosures(connection, days=days)
        freshness = queries.get_data_freshness(
            connection, "dart_disclosures", "dart_sync", "fetched_at"
        )
        analyses = {
            d["id"]: queries.get_disclosure_analysis(connection, d["id"])
            for d in disclosures
        }
        return render_template(
            "disclosures.html",
            disclosures=disclosures,
            analyses=analyses,
            days=days,
            disclosure_checked_at=official_document_manager.datetime_minute(
                freshness["checked_at"]
            ) if freshness["checked_at"] else None,
            disclosure_changed_at=official_document_manager.datetime_minute(
                freshness["changed_at"]
            ) if freshness["changed_at"] else None,
            disclosure_check_status=freshness["check_status"],
        )
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
        legislative_bills = queries.list_legislative_bills(connection, limit=50)
        government_notices = queries.list_government_legislative_notices(
            connection, limit=50
        )
        for law in monitored_laws:
            law["source_url"] = f"https://www.law.go.kr/법령/{quote(law['law_name'])}"
        for update in updates:
            update["source_url"] = f"https://www.law.go.kr/법령/{quote(update['law_name'])}"
        return render_template(
            "laws.html",
            updates=updates,
            monitored_laws=monitored_laws,
            legislative_bills=legislative_bills,
            government_notices=government_notices,
            casino_rules_url="https://www.law.go.kr/행정규칙/카지노업영업준칙",
            casino_rules_annex_url="https://www.law.go.kr/법령/관광진흥법시행규칙/제36조",
            law_checked_at=(
                official_document_manager.datetime_minute(latest_law_checked_at)
                if latest_law_checked_at else None
            ),
            law_changed_at=official_document_manager.datetime_minute(
                latest_law_row["updated_at"]
            ) if latest_law_row and latest_law_row["updated_at"] else None,
            law_check_status=latest_law_sync.get("status") if latest_law_sync else None,
        )
    finally:
        connection.close()


# ============================================================
# 회사 360도 비교
# ============================================================

@app.route("/companies")
def companies_page():
    try:
        days = max(30, min(int(request.args.get("days", 90)), 365))
    except (TypeError, ValueError):
        days = 90
    connection = dashboard_db()
    try:
        companies = company_intelligence.build_company_comparison(connection, days=days)
        return render_template("companies.html", companies=companies, days=days)
    finally:
        connection.close()


# ============================================================
# 리서치
# ============================================================

def _library_context(connection, error=None):
    return {
        "documents": queries.list_research_documents(connection),
        "companies": queries.list_monitored_companies(connection),
        "selected_company": (request.args.get("company") or "").strip(),
        "csrf_token": get_csrf_token(),
        "error": error,
        "notice": (request.args.get("notice") or "").strip(),
    }


@app.route("/library", methods=["GET", "POST"])
def research_library_page():
    if request.method == "POST" and not session.get("user_id"):
        return redirect(
            url_for("auth.login", next=f"{request.script_root}{request.path}")
        )
    connection = dashboard_db()
    saved_file = None
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
        if saved_file:
            document_library.remove_file(saved_file)
        logger.exception("리서치 업로드 처리 실패")
        return render_template(
            "library.html",
            **_library_context(connection, "자료 처리 중 오류가 발생했습니다."),
        ), 500
    finally:
        connection.close()


@app.route("/library/<int:document_id>/download")
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


@app.route("/library/<int:document_id>/reanalyze", methods=["POST"])
@login_required
def reanalyze_research_document(document_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        return redirect(url_for("research_library_page"))
    connection = dashboard_db()
    try:
        document = queries.get_research_document(connection, document_id)
        if not document:
            abort(404)
        analysis, error = ai_insights.analyze_research_document(connection, document)
        queries.update_research_document_analysis(
            connection, document_id, analysis=analysis, error_message=error
        )
        notice = "AI 재분석이 완료되었습니다." if analysis else f"재분석 실패: {error}"
        return redirect(url_for("research_library_page", notice=notice))
    finally:
        connection.close()


@app.route("/library/<int:document_id>/title", methods=["POST"])
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


@app.route("/library/<int:document_id>/delete", methods=["POST"])
@login_required
def delete_research_document(document_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        return redirect(url_for("research_library_page"))
    connection = dashboard_db()
    try:
        document = queries.get_research_document(connection, document_id)
        if not document:
            abort(404)
        document_library.remove_file(document["stored_filename"])
        queries.delete_research_document(connection, document_id)
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
    requested_sources = request.args.getlist("source")
    valid_sources = set(unified_search.SOURCE_LABELS)
    selected_sources = [source for source in requested_sources if source in valid_sources]
    if not selected_sources:
        selected_sources = list(unified_search.SOURCE_LABELS)

    connection = dashboard_db()
    try:
        public_sources = {"news", "disclosure", "law", "insight", "research"}
        if not session.get("user_id"):
            selected_sources = [
                source for source in selected_sources if source in public_sources
            ]
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
            for source in unified_search.SOURCE_LABELS
        }
        return render_template(
            "search.html",
            term=term,
            days=days,
            results=results,
            counts=counts,
            source_labels=unified_search.SOURCE_LABELS,
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

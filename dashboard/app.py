"""
경영기획 인텔리전스 대시보드 - Flask 엔트리포인트.

기존 portfolio/app.py의 세션 쿠키 보안 설정 패턴을 재사용한다.
뉴스 DB는 읽기 전용으로만 연결하고 대시보드 자체 데이터만 dashboard.db에 쓴다.
"""

import secrets
from datetime import timedelta
from urllib.parse import quote

from flask import (
    Flask, abort, g, jsonify, redirect, render_template, request, send_file,
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
    company_intelligence,
    document_library,
    news_reader,
    official_document_manager,
    security_audit,
    telegram_alert,
    unified_search,
)
from official_docs import official_docs_bp
from tips import tips_bp
from utils import escape_html, setup_logger, today_kst_str

logger = setup_logger("dashboard_app")

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

if not config.FLASK_SECRET_KEY:
    logger.warning("FLASK_SECRET_KEY가 설정되지 않아 임시 키를 사용합니다. 재시작 시 세션이 모두 만료됩니다.")

app.register_blueprint(auth_bp)
app.register_blueprint(official_docs_bp)
app.register_blueprint(tips_bp)

ENDPOINT_PERMISSIONS = {
    "performance_page": "performance",
    "disclosures_page": "disclosures",
    "laws_page": "laws",
    "companies_page": "companies",
    "research_library_page": "research_library",
    "download_research_document": "research_library",
    "reanalyze_research_document": "research_library",
    "delete_research_document": "research_library",
    "unified_search_page": "unified_search",
}


@app.before_request
def establish_request_security():
    host = request.host.split(":", 1)[0].lower()
    if not app.testing and host not in config.TRUSTED_HOSTS:
        abort(400)
    g.csp_nonce = secrets.token_urlsafe(18)


@app.after_request
def apply_security_headers(response):
    nonce = getattr(g, "csp_nonce", "")
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "; ".join((
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}'",
        "script-src-attr 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "font-src 'self' https://cdn.jsdelivr.net data:",
        "img-src 'self' data:",
        "connect-src 'self'",
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
                    "path": request.path[:500],
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
        "action_items_page": "버그 제보",
        "performance_page": "실적",
        "disclosures_page": "공시·재무",
        "laws_page": "법률·규제",
        "companies_page": "기업 360°",
        "research_library_page": "리서치",
        "download_research_document": "리서치",
        "reanalyze_research_document": "리서치",
        "delete_research_document": "리서치",
        "unified_search_page": "통합검색",
        "sitemap_page": "사이트맵",
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
    return {
        "current_username": session.get("username"),
        "now_str": today_kst_str(),
        "current_user_role": role or "anonymous",
        "menu_permissions": current_menu_permissions(),
        "csp_nonce": getattr(g, "csp_nonce", ""),
        "global_csrf_token": get_csrf_token(),
        "current_menu_name": current_menu_name,
    }


def _site_map_links():
    """현재 로그인 상태와 메뉴 권한에 맞는 사이트맵 링크를 반환한다."""
    links = [
        {"label": "시작 화면", "description": "공개 메뉴와 로그인 안내", "endpoint": "public_home"},
    ]
    if not session.get("user_id"):
        links.extend([
            {"label": "로그인", "description": "대시보드 계정으로 접속", "endpoint": "auth.login"},
            {"label": "가입 신청", "description": "새 계정 승인 요청", "endpoint": "auth.register"},
        ])
        return links

    permissions = current_menu_permissions()
    links.append(
        {"label": "홈", "description": "업무 현황 종합 대시보드", "endpoint": "dashboard_home"}
    )
    menu_links = (
        ("official_docs", "공문·자료관리", "접수·처리·Y디스크 보관", "official_docs.dashboard"),
        ("performance", "실적", "실적 자료와 지표 확인", "performance_page"),
        ("disclosures", "공시·재무", "DART 공시 및 재무정보", "disclosures_page"),
        ("laws", "법률·규제", "카지노 관련 법령 모니터링", "laws_page"),
        ("companies", "기업 360°", "회사별 통합 기업분석", "companies_page"),
        ("research_library", "리서치", "기업·산업 리포트 분석", "research_library_page"),
        ("unified_search", "통합검색", "뉴스·공시·법령·자료 검색", "unified_search_page"),
        ("tips", "자료실", "업무 노하우와 자동화 자료", "tips.list_page"),
        ("bug_reports", "버그 제보", "오류 등록 및 처리현황", "action_items_page"),
    )
    links.extend(
        {
            "label": label,
            "description": description,
            "endpoint": endpoint,
            "locked": not permissions.get(permission, False),
        }
        for permission, label, description, endpoint in menu_links
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
    return render_template("public_home.html")


@app.route("/dashboard")
@login_required
def dashboard_home():
    today = today_kst_str()
    connection = dashboard_db()
    try:
        bug_report_owner = (
            None if session.get("role") == "admin"
            else (session.get("username") or "")
        )
        important_news = news_reader.today_important_articles()
        official_documents, _ = official_document_manager.list_documents(
            connection, per_page=100000
        )
        official_overdue = [
            item for item in official_documents
            if "접수 후 7일 경과" in item["review_reasons"]
        ]

        kpis = {
            "today_news": news_reader.count_today_articles(),
            "important_news": news_reader.count_today_important_articles(),
            "important_news_delta": _percent_delta(
                news_reader.count_today_important_articles(),
                news_reader.count_yesterday_important_articles(),
            ),
            "pending_action_items": queries.count_action_items(
                connection, reported_by=bug_report_owner
            ),
            "urgent_action_items": queries.count_action_items(
                connection, urgent_only=True, reported_by=bug_report_owner
            ),
            "overdue_action_items": queries.count_action_items(
                connection, overdue_only=True, reported_by=bug_report_owner
            ),
            "new_competitor_issues": news_reader.count_new_issues_today_by_category(
                COMPETITOR_CATEGORY_KEYWORDS
            ),
            "new_policy_issues": news_reader.count_new_issues_today_by_category(
                POLICY_CATEGORY_KEYWORDS
            ),
            "ai_insights_count": queries.count_insights_for_date(connection, today),
        }

        insights = queries.list_insights_for_date(connection, today)
        action_items = queries.list_action_items(
            connection, reported_by=bug_report_owner
        )[:10]
        latest_performance = queries.get_latest_performance_report(connection, today)
        recent_disclosures = queries.list_recent_disclosures(connection, days=7)[:10]
        recent_law_updates = queries.list_recent_law_updates(connection, days=30)[:10]
        news_updated_raw = news_reader.last_updated_at()
        official_update_status = official_document_manager.data_update_status(connection)

        return render_template(
            "dashboard.html",
            kpis=kpis,
            important_news=important_news[:12],
            official_metrics=official_document_manager.dashboard_metrics(connection),
            official_overdue=official_overdue[:10],
            official_recent=official_documents[:6],
            insights=insights,
            action_items=action_items,
            latest_performance=latest_performance,
            recent_disclosures=recent_disclosures,
            recent_law_updates=recent_law_updates,
            csrf_token=get_csrf_token(),
            casino_news_updated_at=(
                official_document_manager.datetime_minute(news_updated_raw)
                if news_updated_raw else None
            ),
            official_db_updated_at=(
                official_document_manager.datetime_minute(
                    official_update_status["latest_updated_at"]
                )
                if official_update_status["latest_updated_at"]
                else None
            ),
        )
    finally:
        connection.close()


# ============================================================
# Action Items
# ============================================================

@app.route("/action-items", methods=["GET", "POST"])
@app.route("/bug-reports", methods=["GET", "POST"])
@login_required
def action_items_page():
    connection = dashboard_db()
    try:
        is_admin = session.get("role") == "admin"
        username = session.get("username") or ""

        def visible_items(status=None):
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
                return render_template("action_items.html", error="버그 제목을 입력해주세요.",
                                        items=visible_items(), csrf_token=get_csrf_token(),
                                        is_admin=is_admin), 400

            description = (request.form.get("description") or "").strip()
            priority = request.form.get("priority") or "보통"
            bug_page = (request.form.get("bug_page") or "").strip()
            environment = (request.form.get("environment") or "").strip()
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
            )
            bug_url = request.url_root.rstrip("/") + url_for("action_items_page")
            alert_lines = [
                "🐞 <b>새 버그 제보</b>",
                "",
                f"<b>제목:</b> {escape_html(title)}",
                f"<b>심각도:</b> {escape_html(priority)}",
                f"<b>제보자:</b> {escape_html(reporter or '-')}",
                f"<b>발생 화면:</b> {escape_html(bug_page or '-')}",
                f"<b>사용 환경:</b> {escape_html(environment or '-')}",
                "",
                escape_html(description[:800] or "상세 내용 없음"),
                "",
                f'<a href="{bug_url}">버그 제보 페이지 열기</a> · #{item_id}',
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
        is_reporter = (
            bool(session.get("username"))
            and item.get("reported_by") == session.get("username")
        )
        if not is_admin and not is_reporter:
            abort(403)

        fields = {}
        allowed_fields = (
            ("status", "priority", "owner", "memo", "title", "description",
             "bug_page", "environment")
            if is_admin
            else ("priority", "title", "description", "bug_page", "environment")
        )
        for key in allowed_fields:
            if key in request.form:
                fields[key] = (request.form.get(key) or "").strip()
        if "title" in fields and not fields["title"]:
            abort(400)
        if fields:
            queries.update_action_item(connection, item_id, **fields)
        if is_admin and request.form.get("approve") == "1":
            queries.approve_action_item(connection, item_id)
    finally:
        connection.close()
    return redirect(url_for("action_items_page"))


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

@app.route("/performance")
@login_required
def performance_page():
    connection = dashboard_db()
    try:
        report_date = request.args.get("date") or today_kst_str()
        reports = queries.list_performance_reports(connection, report_date)
        return render_template("performance.html", reports=reports, report_date=report_date)
    finally:
        connection.close()


# ============================================================
# 공시·재무
# ============================================================

@app.route("/disclosures")
@login_required
def disclosures_page():
    connection = dashboard_db()
    try:
        days = int(request.args.get("days", 7))
        disclosures = queries.list_recent_disclosures(connection, days=days)
        latest_dart_sync = queries.get_last_successful_run(connection, "dart_sync")
        analyses = {
            d["id"]: queries.get_disclosure_analysis(connection, d["id"])
            for d in disclosures if d["is_important"]
        }
        return render_template(
            "disclosures.html",
            disclosures=disclosures,
            analyses=analyses,
            days=days,
            disclosure_updated_at=(
                official_document_manager.datetime_minute(latest_dart_sync["finished_at"])
                if latest_dart_sync and latest_dart_sync.get("finished_at") else None
            ),
        )
    finally:
        connection.close()


# ============================================================
# 법률·규제
# ============================================================

@app.route("/laws")
@login_required
def laws_page():
    connection = dashboard_db()
    try:
        updates = queries.list_recent_law_updates(connection, days=90)
        latest_law_sync = queries.get_last_successful_run(connection, "law_sync")
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
            updates=updates,
            monitored_laws=monitored_laws,
            casino_rules_url="https://www.law.go.kr/행정규칙/카지노업영업준칙",
            casino_rules_annex_url="https://www.law.go.kr/법령/관광진흥법시행규칙/제36조",
            law_updated_at=(
                official_document_manager.datetime_minute(latest_law_checked_at)
                if latest_law_checked_at else None
            ),
        )
    finally:
        connection.close()


# ============================================================
# 회사 360도 비교
# ============================================================

@app.route("/companies")
@login_required
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
@login_required
def research_library_page():
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
            company_names = list(dict.fromkeys(
                name.strip() for name in request.form.getlist("company_names")
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

            title = (request.form.get("title") or "").strip()[:200]
            if not title:
                title = extracted["original_filename"].rsplit(".", 1)[0]

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
@login_required
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
@login_required
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

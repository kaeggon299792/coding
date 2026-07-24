"""
경영기획 인텔리전스 대시보드 - Flask 엔트리포인트.

기존 portfolio/app.py의 세션 쿠키 보안 설정 패턴을 재사용한다. 뉴스/이메일
DB는 읽기 전용으로만 연결하고(services/news_reader.py, email_reader.py),
대시보드 자체 데이터만 dashboard.db에 쓴다.
"""

from datetime import timedelta

from flask import Flask, redirect, render_template, request, session, url_for

import config
from auth import auth_bp, get_csrf_token, login_required, validate_csrf
from dashboard_db import queries
from extensions import dashboard_db
from services import email_reader, news_reader
from utils import setup_logger, today_kst_str

logger = setup_logger("dashboard_app")

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY or "dev-only-insecure-key-set-FLASK_SECRET_KEY"
app.permanent_session_lifetime = timedelta(days=config.SESSION_LIFETIME_DAYS)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=True,
)

if not config.FLASK_SECRET_KEY:
    logger.warning("FLASK_SECRET_KEY가 설정되지 않아 임시 키를 사용합니다. 재시작 시 세션이 모두 만료됩니다.")

app.register_blueprint(auth_bp)

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
    return {
        "current_username": session.get("username"),
        "now_str": today_kst_str(),
    }


def _percent_delta(today_value, prev_value):
    if prev_value in (None, 0):
        return None
    return round(((today_value - prev_value) / prev_value) * 100)


@app.route("/")
@login_required
def dashboard_home():
    today = today_kst_str()
    connection = dashboard_db()
    try:
        important_news = news_reader.today_important_articles()
        important_emails = email_reader.today_important_emails()

        kpis = {
            "today_news": news_reader.count_today_articles(),
            "important_news": news_reader.count_today_important_articles(),
            "important_news_delta": _percent_delta(
                news_reader.count_today_important_articles(),
                news_reader.count_yesterday_important_articles(),
            ),
            "important_emails": email_reader.count_today_important_emails(),
            "important_emails_delta": _percent_delta(
                email_reader.count_today_important_emails(),
                email_reader.count_yesterday_important_emails(),
            ),
            "urgent_emails": email_reader.count_today_urgent_emails(),
            "pending_action_items": queries.count_action_items(connection),
            "due_today_action_items": queries.count_action_items(connection, due_today_only=True),
            "overdue_action_items": queries.count_action_items(connection, overdue_only=True),
            "new_competitor_issues": news_reader.count_new_issues_today_by_category(
                COMPETITOR_CATEGORY_KEYWORDS
            ),
            "new_policy_issues": news_reader.count_new_issues_today_by_category(
                POLICY_CATEGORY_KEYWORDS
            ),
            "ai_insights_count": queries.count_insights_for_date(connection, today),
        }

        insights = queries.list_insights_for_date(connection, today)
        action_items = queries.list_action_items(connection)[:10]
        latest_performance = queries.get_latest_performance_report(connection, today)
        recent_disclosures = queries.list_recent_disclosures(connection, days=7)[:10]
        recent_law_updates = queries.list_recent_law_updates(connection, days=30)[:10]

        return render_template(
            "dashboard.html",
            kpis=kpis,
            important_news=important_news[:12],
            important_emails=important_emails[:12],
            insights=insights,
            action_items=action_items,
            latest_performance=latest_performance,
            recent_disclosures=recent_disclosures,
            recent_law_updates=recent_law_updates,
            csrf_token=get_csrf_token(),
        )
    finally:
        connection.close()


# ============================================================
# Action Items
# ============================================================

@app.route("/action-items", methods=["GET", "POST"])
@login_required
def action_items_page():
    connection = dashboard_db()
    try:
        if request.method == "POST":
            if not validate_csrf(request.form.get("csrf_token", "")):
                return render_template("action_items.html", error="요청이 만료되었습니다. 다시 시도해주세요.",
                                        items=queries.list_action_items(connection), csrf_token=get_csrf_token()), 400

            title = (request.form.get("title") or "").strip()
            if not title:
                return render_template("action_items.html", error="과제명을 입력해주세요.",
                                        items=queries.list_action_items(connection), csrf_token=get_csrf_token()), 400

            queries.create_action_item(
                connection,
                title=title,
                description=(request.form.get("description") or "").strip(),
                owner=(request.form.get("owner") or "").strip() or None,
                due_date=(request.form.get("due_date") or "").strip() or None,
                due_date_confidence=request.form.get("due_date_confidence") or "unclear",
                priority=request.form.get("priority") or "normal",
            )
            return redirect(url_for("action_items_page"))

        status_filter = request.args.get("status") or None
        items = queries.list_action_items(connection, status=status_filter)
        return render_template("action_items.html", items=items, csrf_token=get_csrf_token(),
                                status_filter=status_filter)
    finally:
        connection.close()


@app.route("/action-items/<int:item_id>/update", methods=["POST"])
@login_required
def update_action_item_route(item_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        return redirect(url_for("action_items_page"))

    connection = dashboard_db()
    try:
        fields = {}
        for key in ("status", "priority", "owner", "memo", "due_date"):
            if key in request.form:
                fields[key] = request.form.get(key)
        if fields:
            queries.update_action_item(connection, item_id, **fields)
        if request.form.get("approve") == "1":
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
        analyses = {
            d["id"]: queries.get_disclosure_analysis(connection, d["id"])
            for d in disclosures if d["is_important"]
        }
        return render_template("disclosures.html", disclosures=disclosures, analyses=analyses, days=days)
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
        return render_template("laws.html", updates=updates)
    finally:
        connection.close()


@app.route("/healthz")
def healthz():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)

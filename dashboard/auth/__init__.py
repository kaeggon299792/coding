"""
로그인/로그아웃, 세션 인증, CSRF 보호.

기존 portfolio/app.py의 세션 쿠키 설정(HttpOnly/Secure/SameSite=Lax)과 로그인
시도 제한 패턴을 참고하되, 비밀번호는 평문 비교가 아니라 werkzeug의 해시로
저장/검증한다(스펙이 명시적으로 해시 저장을 요구함).
"""

import secrets
import json
import re
import sqlite3
import hashlib
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from dashboard_db import queries
from extensions import dashboard_db
from services import security_audit
import config
from utils import now_kst

auth_bp = Blueprint("auth", __name__)

LOGIN_IP_MAX_FAILURES = 10
SESSION_IDLE_TIMEOUT = timedelta(minutes=config.SESSION_IDLE_MINUTES)
SESSION_ABSOLUTE_TIMEOUT = timedelta(hours=config.SESSION_ABSOLUTE_HOURS)

MENU_PERMISSIONS = {
    "bug_reports": "버그 및 Q&A",
    "disclosures": "공시·재무",
    "laws": "법률·규제",
    "companies": "기업 360°",
    "research_library": "리서치",
    "official_docs": "공문·자료관리",
    "unified_search": "통합검색",
    "tips": "자료실",
}
LANDING_ENDPOINTS = {
    "dashboard": "dashboard_home",
    "bug_reports": "action_items_page",
    "performance": "tourism_trend_page",
    "disclosures": "disclosures_page",
    "laws": "laws_page",
    "companies": "companies_page",
    "research_library": "research_library_page",
    "official_docs": "official_docs.dashboard",
    "unified_search": "unified_search_page",
    "tips": "tips.list_page",
}


def current_menu_permissions():
    if not session.get("user_id"):
        return {code: False for code in MENU_PERMISSIONS}
    connection = dashboard_db()
    try:
        user = connection.execute(
            "SELECT role, is_active FROM dashboard_users WHERE id=?",
            (session["user_id"],),
        ).fetchone()
        if user:
            session["role"] = user["role"] or "user"
            if session["role"] == "admin":
                return {code: True for code in MENU_PERMISSIONS}
        return queries.get_user_permissions(
            connection, session["user_id"], MENU_PERMISSIONS.keys()
        )
    finally:
        connection.close()


def _client_ip():
    # PythonAnywhere supplies the real client address to Flask as remote_addr.
    return (request.remote_addr or "unknown").strip()[:100]


def _ip_security_row(connection, ip):
    row = connection.execute(
        "SELECT * FROM login_ip_security WHERE ip_address=?", (ip,)
    ).fetchone()
    return dict(row) if row else None


def _record_failed_attempt(connection, ip):
    now_iso = now_kst().isoformat()
    current = _ip_security_row(connection, ip)
    attempts = (current["failed_attempts"] if current else 0) + 1
    blocked_at = (
        current.get("blocked_at") if current else None
    ) or (now_iso if attempts >= LOGIN_IP_MAX_FAILURES else None)
    connection.execute(
        """
        INSERT INTO login_ip_security
            (ip_address, failed_attempts, first_failed_at, last_failed_at,
             blocked_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(ip_address) DO UPDATE SET
            failed_attempts=excluded.failed_attempts,
            last_failed_at=excluded.last_failed_at,
            blocked_at=excluded.blocked_at,
            updated_at=excluded.updated_at
        """,
        (
            ip, attempts,
            current.get("first_failed_at") if current else now_iso,
            now_iso, blocked_at, now_iso,
        ),
    )
    connection.commit()
    return attempts, bool(blocked_at)


def _reset_failed_attempts(connection, ip):
    connection.execute(
        """
        UPDATE login_ip_security SET failed_attempts=0, first_failed_at=NULL,
            last_failed_at=NULL, updated_at=?
        WHERE ip_address=? AND blocked_at IS NULL
        """,
        (now_kst().isoformat(), ip),
    )
    connection.commit()


def get_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


def validate_csrf(token):
    expected = session.get("csrf_token")
    return bool(expected) and bool(token) and secrets.compare_digest(expected, token)


def _session_hash(raw_session_id):
    return hashlib.sha256(str(raw_session_id or "").encode("utf-8")).hexdigest()


def _revoke_user_sessions(connection, user_id, reason, except_session_hash=None):
    now_iso = now_kst().isoformat()
    if except_session_hash:
        connection.execute(
            """
            UPDATE dashboard_active_sessions
            SET revoked_at=?, revoke_reason=?
            WHERE user_id=? AND revoked_at IS NULL AND session_hash<>?
            """,
            (now_iso, reason, user_id, except_session_hash),
        )
    else:
        connection.execute(
            """
            UPDATE dashboard_active_sessions
            SET revoked_at=?, revoke_reason=?
            WHERE user_id=? AND revoked_at IS NULL
            """,
            (now_iso, reason, user_id),
        )


def _revoke_current_session(connection, reason):
    raw_session_id = session.get("session_id")
    if raw_session_id:
        connection.execute(
            """
            UPDATE dashboard_active_sessions
            SET revoked_at=?, revoke_reason=?
            WHERE session_hash=? AND revoked_at IS NULL
            """,
            (now_kst().isoformat(), reason, _session_hash(raw_session_id)),
        )


def _session_is_valid(connection, user):
    raw_session_id = session.get("session_id")
    if not raw_session_id:
        return bool(current_app.testing)
    row = connection.execute(
        "SELECT * FROM dashboard_active_sessions WHERE session_hash=? AND user_id=?",
        (_session_hash(raw_session_id), session.get("user_id")),
    ).fetchone()
    if not row or row["revoked_at"]:
        return False
    now = now_kst()
    try:
        last_seen = datetime.fromisoformat(row["last_seen_at"])
        absolute_expires = datetime.fromisoformat(row["absolute_expires_at"])
        password_changed = (
            datetime.fromisoformat(user["password_changed_at"])
            if user["password_changed_at"] else None
        )
        created_at = datetime.fromisoformat(row["created_at"])
    except (TypeError, ValueError):
        _revoke_current_session(connection, "invalid_session_timestamp")
        return False
    if now - last_seen > SESSION_IDLE_TIMEOUT:
        _revoke_current_session(connection, "idle_timeout")
        return False
    if now >= absolute_expires:
        _revoke_current_session(connection, "absolute_timeout")
        return False
    if password_changed and password_changed > created_at:
        _revoke_current_session(connection, "password_changed")
        return False
    connection.execute(
        "UPDATE dashboard_active_sessions SET last_seen_at=? WHERE session_hash=?",
        (now.isoformat(), row["session_hash"]),
    )
    return True


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify({"success": False, "message": "로그인이 필요합니다."}), 401
            return redirect(url_for("auth.login", next=request.path))
        connection = dashboard_db()
        try:
            user = connection.execute(
                """
                SELECT username, role, is_active, password_changed_at
                FROM dashboard_users WHERE id = ?
                """,
                (session["user_id"],),
            ).fetchone()
            testing_legacy_session = (
                current_app.testing and not session.get("session_id") and not user
            )
            if not testing_legacy_session and (
                not user or not user["is_active"] or not _session_is_valid(connection, user)
            ):
                _revoke_current_session(connection, "account_or_session_invalid")
                connection.commit()
                session.clear()
                if request.path.startswith("/api/"):
                    return jsonify({"success": False, "message": "세션이 만료되었습니다."}), 401
                return redirect(url_for("auth.login", expired="1"))
            connection.commit()
        finally:
            connection.close()
        # Existing internal/test sessions may predate the account table. When a
        # real account exists, its latest active state and role are authoritative.
        if user:
            session["username"] = user["username"]
            session["role"] = user["role"] or "user"
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        response = login_required(lambda: None)()
        if response is not None:
            return response
        if session.get("role") != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def _audit_user(connection, target, action, detail=None):
    connection.execute(
        """
        INSERT INTO dashboard_user_audit
            (target_user_id, target_username, action, actor_user_id,
             actor_username, detail_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            target["id"] if target else None,
            target["username"] if target else "unknown",
            action, session.get("user_id"), session.get("username") or "unknown",
            json.dumps(detail or {}, ensure_ascii=False), now_kst().isoformat(),
        ),
    )
    security_audit.log_event(
        connection,
        action,
        "dashboard_user",
        target["id"] if target else None,
        {"target_username": target["username"] if target else "unknown", **(detail or {})},
    )


def _valid_password(password):
    return (
        len(password) >= 10
        and re.search(r"[A-Za-z]", password)
        and re.search(r"\d", password)
        and re.search(r"[^A-Za-z0-9]", password)
    )


def _landing_page_for_user(connection, user):
    landing_page = user.get("landing_page") or "dashboard"
    role = user.get("role") or "user"
    if (
        landing_page != "dashboard"
        and role != "admin"
        and not queries.get_user_permissions(
            connection, user["id"], MENU_PERMISSIONS.keys()
        ).get(landing_page, False)
    ):
        return "dashboard"
    return landing_page


def _start_user_session(connection, user):
    session.clear()
    raw_session_id = secrets.token_urlsafe(32)
    now = now_kst()
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["role"] = user.get("role") or "user"
    session["session_id"] = raw_session_id
    session.permanent = True
    connection.execute(
        """
        INSERT INTO dashboard_active_sessions
            (session_hash, user_id, username, ip_address, user_agent, created_at,
             last_seen_at, absolute_expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _session_hash(raw_session_id), user["id"], user["username"], _client_ip(),
            str(request.user_agent.string or "")[:500], now.isoformat(), now.isoformat(),
            (now + SESSION_ABSOLUTE_TIMEOUT).isoformat(),
        ),
    )


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    values = {
        "username": (request.form.get("username") or "").strip(),
        "email": (request.form.get("email") or "").strip().lower(),
    }
    if request.method == "GET":
        return render_template(
            "register.html", csrf_token=get_csrf_token(), values=values
        )
    if not validate_csrf(request.form.get("csrf_token", "")):
        return render_template(
            "register.html", csrf_token=get_csrf_token(), values=values,
            error="요청이 만료되었습니다. 다시 시도해주세요.",
        ), 400

    username = values["username"]
    email = values["email"]
    password = request.form.get("password") or ""
    error = None
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,40}", username):
        error = "아이디는 영문·숫자·점·밑줄·하이픈으로 3~40자여야 합니다."
    elif not re.fullmatch(r"[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{2,}", email):
        error = "이메일 형식을 확인해주세요."
    elif not _valid_password(password):
        error = "비밀번호는 10자 이상이며 영문·숫자·특수문자를 포함해야 합니다."

    connection = dashboard_db()
    try:
        since = (now_kst() - timedelta(days=1)).isoformat()
        recent_count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM security_audit_log
            WHERE action='SELF_REGISTRATION' AND ip_address=? AND created_at>=?
            """,
            (_client_ip(), since),
        ).fetchone()["count"]
        if recent_count >= 5:
            error = "이 IP에서 가입 신청이 너무 많습니다. 관리자에게 문의해주세요."
        duplicate = connection.execute(
            """
            SELECT 1 FROM dashboard_users
            WHERE LOWER(username)=LOWER(?) OR LOWER(email)=LOWER(?)
            LIMIT 1
            """,
            (username, email),
        ).fetchone()
        if duplicate:
            error = "이미 사용 중인 아이디 또는 이메일입니다."
        if error:
            return render_template(
                "register.html", csrf_token=get_csrf_token(), values=values, error=error
            ), 400

        now_iso = now_kst().isoformat()
        cursor = connection.execute(
            """
            INSERT INTO dashboard_users
                (username, email, password_hash, role, is_active, created_at,
                 updated_at, password_changed_at, landing_page, approval_status)
            VALUES (?, ?, ?, 'user', 0, ?, ?, ?, 'dashboard', 'pending')
            """,
            (
                username, email, generate_password_hash(password, method="scrypt"),
                now_iso, now_iso, now_iso,
            ),
        )
        default_permissions = {"bug_reports", "disclosures", "laws", "companies"}
        queries.replace_user_permissions(
            connection, cursor.lastrowid, MENU_PERMISSIONS.keys(),
            default_permissions, None,
        )
        security_audit.log_event(
            connection,
            "SELF_REGISTRATION",
            "dashboard_user",
            cursor.lastrowid,
            {"username": username, "approval_status": "pending"},
        )
        connection.commit()
        return redirect(url_for("auth.login", registered="1"))
    except sqlite3.IntegrityError:
        connection.rollback()
        return render_template(
            "register.html", csrf_token=get_csrf_token(), values=values,
            error="이미 사용 중인 아이디 또는 이메일입니다.",
        ), 409
    finally:
        connection.close()


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template(
            "login.html",
            csrf_token=get_csrf_token(),
            error=(
                "보안을 위해 로그인 세션이 종료되었습니다. 다시 로그인해주세요."
                if request.args.get("expired") == "1" else None
            ),
            notice=(
                "가입 신청이 접수되었습니다. 관리자가 승인하면 로그인할 수 있습니다."
                if request.args.get("registered") == "1" else None
            ),
        )

    submitted_token = request.form.get("csrf_token", "")
    if not validate_csrf(submitted_token):
        return render_template(
            "login.html", csrf_token=get_csrf_token(), error="요청이 만료되었습니다. 다시 시도해주세요."
        ), 400

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    ip = _client_ip()
    landing_page = "dashboard"
    connection = dashboard_db()
    try:
        ip_status = _ip_security_row(connection, ip)
        if ip_status and ip_status.get("blocked_at"):
            security_audit.log_event(
                connection, "LOGIN_BLOCKED", "dashboard_user", None,
                {"attempted_username": username}, success=False,
            )
            connection.commit()
            return render_template(
                "login.html", csrf_token=get_csrf_token(),
                error="이 IP는 로그인 실패 10회로 차단되었습니다. 관리자에게 해제를 요청해주세요.",
            ), 403
        user = queries.get_user_by_username(connection, username)
        if (
            not user or not user.get("is_active", 1)
            or not check_password_hash(user["password_hash"], password)
        ):
            attempts, blocked = _record_failed_attempt(connection, ip)
            security_audit.log_event(
                connection, "LOGIN_FAILED", "dashboard_user",
                user["id"] if user else None,
                {
                    "attempted_username": username,
                    "failed_attempts": attempts,
                    "ip_blocked": blocked,
                },
                success=False,
            )
            connection.commit()
            remaining = max(0, LOGIN_IP_MAX_FAILURES - attempts)
            return render_template(
                "login.html", csrf_token=get_csrf_token(),
                error=(
                    "로그인 실패 10회로 해당 IP가 차단되었습니다."
                    if blocked else
                    f"아이디 또는 비밀번호가 올바르지 않습니다. 차단까지 {remaining}회 남았습니다."
                ),
            ), 403 if blocked else 401

        _start_user_session(connection, user)
        landing_page = _landing_page_for_user(connection, user)
        _reset_failed_attempts(connection, ip)
        queries.touch_last_login(connection, user["id"])
        security_audit.log_event(
            connection, "LOGIN_SUCCESS", "dashboard_user", user["id"],
            {"landing_page": landing_page},
        )
        connection.commit()
    finally:
        connection.close()

    next_path = request.args.get("next") or url_for(
        LANDING_ENDPOINTS.get(landing_page, "dashboard_home")
    )
    return redirect(next_path)


@auth_bp.route("/login/test", methods=["POST"])
def test_login():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        ip_status = _ip_security_row(connection, _client_ip())
        if ip_status and ip_status.get("blocked_at"):
            return render_template(
                "login.html", csrf_token=get_csrf_token(),
                error="이 IP는 차단되어 테스트 계정도 사용할 수 없습니다.",
            ), 403
        user = queries.get_user_by_username(connection, "test")
        if not user or not user.get("is_active", 1) or (user.get("role") or "user") != "user":
            return render_template(
                "login.html",
                csrf_token=get_csrf_token(),
                error="테스트 계정을 사용할 수 없습니다. 관리자에게 문의해주세요.",
            ), 403
        _start_user_session(connection, user)
        landing_page = _landing_page_for_user(connection, user)
        queries.touch_last_login(connection, user["id"])
        security_audit.log_event(
            connection, "TEST_LOGIN_SUCCESS", "dashboard_user", user["id"],
            {"landing_page": landing_page},
        )
        connection.commit()
    finally:
        connection.close()
    return redirect(url_for(LANDING_ENDPOINTS.get(landing_page, "dashboard_home")))


@auth_bp.route("/logout", methods=["POST"])
def logout():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        security_audit.log_event(
            connection, "LOGOUT", "dashboard_user", session.get("user_id")
        )
        _revoke_current_session(connection, "user_logout")
        connection.commit()
    finally:
        connection.close()
    session.clear()
    return redirect(url_for("auth.login"))


@auth_bp.route("/admin/users", methods=["GET", "POST"])
@admin_required
def user_management():
    connection = dashboard_db()
    try:
        error = None
        success = request.args.get("success")
        if request.method == "POST":
            if not validate_csrf(request.form.get("csrf_token", "")):
                return render_template("403.html"), 400
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            role = request.form.get("role") or "user"
            if not re.fullmatch(r"[A-Za-z0-9._-]{3,40}", username):
                error = "아이디는 영문·숫자·점·밑줄·하이픈으로 3~40자여야 합니다."
            elif role not in ("admin", "user"):
                error = "권한을 다시 선택해주세요."
            elif not _valid_password(password):
                error = "비밀번호는 10자 이상이며 영문·숫자·특수문자를 포함해야 합니다."
            else:
                try:
                    cursor = connection.execute(
                        """
                        INSERT INTO dashboard_users
                            (username, password_hash, role, is_active, created_at,
                             updated_at, password_changed_at)
                        VALUES (?, ?, ?, 1, ?, ?, ?)
                        """,
                        (
                            username, generate_password_hash(password), role,
                            now_kst().isoformat(), now_kst().isoformat(), now_kst().isoformat(),
                        ),
                    )
                    target = {"id": cursor.lastrowid, "username": username}
                    queries.replace_user_permissions(
                        connection, cursor.lastrowid, MENU_PERMISSIONS.keys(),
                        set(MENU_PERMISSIONS), session.get("user_id"),
                    )
                    _audit_user(connection, target, "ACCOUNT_CREATED", {"role": role})
                    connection.commit()
                    return redirect(url_for("auth.user_management", success="계정을 생성했습니다."))
                except sqlite3.IntegrityError:
                    connection.rollback()
                    error = "이미 사용 중인 아이디입니다."
        users = [
            dict(row) for row in connection.execute(
                """
                SELECT id, username, email, role, is_active, approval_status, created_at, updated_at,
                       last_login_at, password_changed_at, landing_page
                FROM dashboard_users ORDER BY is_active DESC, role, username
                """
            ).fetchall()
        ]
        audit = [
            dict(row) for row in connection.execute(
                "SELECT * FROM dashboard_user_audit ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        ]
        ip_security = [
            dict(row) for row in connection.execute(
                """
                SELECT * FROM login_ip_security
                ORDER BY blocked_at IS NOT NULL DESC, updated_at DESC LIMIT 200
                """
            ).fetchall()
        ]
        security_events = [
            dict(row) for row in connection.execute(
                """
                SELECT * FROM security_audit_log
                ORDER BY created_at DESC LIMIT 200
                """
            ).fetchall()
        ]
        active_sessions = [
            dict(row) for row in connection.execute(
                """
                SELECT session_hash, user_id, username, ip_address, user_agent,
                       created_at, last_seen_at, absolute_expires_at
                FROM dashboard_active_sessions
                WHERE revoked_at IS NULL AND absolute_expires_at>?
                ORDER BY last_seen_at DESC
                LIMIT 200
                """,
                (now_kst().isoformat(),),
            ).fetchall()
        ]
        permission_matrix = {
            user["id"]: (
                {code: True for code in MENU_PERMISSIONS}
                if user["role"] == "admin"
                else queries.get_user_permissions(
                    connection, user["id"], MENU_PERMISSIONS.keys()
                )
            )
            for user in users
        }
        return render_template(
            "user_management.html", users=users, audit=audit, error=error,
            success=success, csrf_token=get_csrf_token(),
            menu_permissions_catalog=MENU_PERMISSIONS,
            permission_matrix=permission_matrix,
            ip_security=ip_security,
            security_events=security_events,
            active_sessions=active_sessions,
            current_session_hash=(
                _session_hash(session.get("session_id")) if session.get("session_id") else None
            ),
            session_idle_minutes=config.SESSION_IDLE_MINUTES,
            session_absolute_hours=config.SESSION_ABSOLUTE_HOURS,
            login_ip_max_failures=LOGIN_IP_MAX_FAILURES,
        )
    finally:
        connection.close()


@auth_bp.route("/admin/users/<int:user_id>/role", methods=["POST"])
@admin_required
def update_user_role(user_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        return render_template("403.html"), 400
    role = request.form.get("role")
    if role not in ("admin", "user"):
        return redirect(url_for("auth.user_management"))
    if user_id == session.get("user_id"):
        return redirect(url_for("auth.user_management", success="본인 권한은 변경할 수 없습니다."))
    connection = dashboard_db()
    try:
        target = connection.execute(
            "SELECT id, username, role FROM dashboard_users WHERE id=?", (user_id,)
        ).fetchone()
        if not target:
            return redirect(url_for("auth.user_management"))
        connection.execute(
            "UPDATE dashboard_users SET role=?, updated_at=? WHERE id=?",
            (role, now_kst().isoformat(), user_id),
        )
        _audit_user(
            connection, target, "ROLE_CHANGED",
            {"before": target["role"], "after": role},
        )
        _revoke_user_sessions(connection, user_id, "role_changed")
        connection.commit()
        return redirect(url_for("auth.user_management", success="권한을 변경했습니다."))
    finally:
        connection.close()


@auth_bp.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def toggle_user_active(user_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        return render_template("403.html"), 400
    if user_id == session.get("user_id"):
        return redirect(url_for("auth.user_management", success="본인 계정은 비활성화할 수 없습니다."))
    connection = dashboard_db()
    try:
        target = connection.execute(
            """
            SELECT id, username, is_active, approval_status
            FROM dashboard_users WHERE id=?
            """,
            (user_id,),
        ).fetchone()
        if not target:
            return redirect(url_for("auth.user_management"))
        new_value = 0 if target["is_active"] else 1
        connection.execute(
            """
            UPDATE dashboard_users
            SET is_active=?, approval_status=?, updated_at=?
            WHERE id=?
            """,
            (
                new_value, "approved" if new_value else "disabled",
                now_kst().isoformat(), user_id,
            ),
        )
        _audit_user(
            connection,
            target,
            (
                "ACCOUNT_APPROVED"
                if new_value and target["approval_status"] == "pending"
                else "ACCOUNT_ACTIVATED" if new_value else "ACCOUNT_DEACTIVATED"
            ),
        )
        if not new_value:
            _revoke_user_sessions(connection, user_id, "account_deactivated")
        connection.commit()
        return redirect(url_for(
            "auth.user_management", success="계정 상태를 변경했습니다."
        ))
    finally:
        connection.close()


@auth_bp.route("/admin/users/<int:user_id>/password", methods=["POST"])
@admin_required
def reset_user_password(user_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        return render_template("403.html"), 400
    password = request.form.get("new_password") or ""
    if not _valid_password(password):
        return redirect(url_for(
            "auth.user_management",
            success="비밀번호는 10자 이상이며 영문·숫자·특수문자가 필요합니다.",
        ))
    connection = dashboard_db()
    try:
        target = connection.execute(
            "SELECT id, username FROM dashboard_users WHERE id=?", (user_id,)
        ).fetchone()
        if not target:
            return redirect(url_for("auth.user_management"))
        connection.execute(
            """
            UPDATE dashboard_users SET password_hash=?, password_changed_at=?, updated_at=?
            WHERE id=?
            """,
            (
                generate_password_hash(password), now_kst().isoformat(),
                now_kst().isoformat(), user_id,
            ),
        )
        _audit_user(connection, target, "PASSWORD_RESET")
        _revoke_user_sessions(connection, user_id, "password_reset")
        connection.commit()
        return redirect(url_for("auth.user_management", success="비밀번호를 초기화했습니다."))
    finally:
        connection.close()


@auth_bp.route("/admin/users/<int:user_id>/permissions", methods=["POST"])
@admin_required
def update_user_permissions(user_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        target = connection.execute(
            "SELECT id, username, role FROM dashboard_users WHERE id=?", (user_id,)
        ).fetchone()
        if not target:
            return redirect(url_for("auth.user_management"))
        landing_page = request.form.get("landing_page") or "dashboard"
        if landing_page not in LANDING_ENDPOINTS:
            landing_page = "dashboard"
        allowed = {
            code for code in request.form.getlist("permissions")
            if code in MENU_PERMISSIONS
        }
        if target["role"] == "admin":
            allowed = set(MENU_PERMISSIONS)
        else:
            queries.replace_user_permissions(
                connection, user_id, MENU_PERMISSIONS.keys(), allowed,
                session.get("user_id"),
            )
            if landing_page != "dashboard" and landing_page not in allowed:
                landing_page = "dashboard"
        connection.execute(
            "UPDATE dashboard_users SET landing_page=?, updated_at=? WHERE id=?",
            (landing_page, now_kst().isoformat(), user_id),
        )
        _audit_user(
            connection, target, "MENU_PERMISSIONS_CHANGED",
            {"allowed": sorted(allowed), "landing_page": landing_page},
        )
        _revoke_user_sessions(connection, user_id, "menu_permissions_changed")
        connection.commit()
        return redirect(url_for(
            "auth.user_management", success=f"{target['username']} 계정의 메뉴 권한을 저장했습니다."
        ))
    finally:
        connection.close()


@auth_bp.route("/admin/security/session/<session_hash>/revoke", methods=["POST"])
@admin_required
def revoke_active_session(session_hash):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    if not re.fullmatch(r"[a-f0-9]{64}", session_hash):
        abort(400)
    connection = dashboard_db()
    try:
        target = connection.execute(
            """
            SELECT session_hash, user_id, username
            FROM dashboard_active_sessions
            WHERE session_hash=? AND revoked_at IS NULL
            """,
            (session_hash,),
        ).fetchone()
        if not target:
            return redirect(url_for("auth.user_management", success="이미 종료된 세션입니다."))
        connection.execute(
            """
            UPDATE dashboard_active_sessions
            SET revoked_at=?, revoke_reason='admin_revoked'
            WHERE session_hash=?
            """,
            (now_kst().isoformat(), session_hash),
        )
        security_audit.log_event(
            connection,
            "SESSION_REVOKED",
            "dashboard_session",
            session_hash[:12],
            {"target_user_id": target["user_id"], "target_username": target["username"]},
        )
        connection.commit()
        if session_hash == _session_hash(session.get("session_id")):
            session.clear()
            return redirect(url_for("auth.login", expired="1"))
        return redirect(url_for("auth.user_management", success="선택한 로그인을 종료했습니다."))
    finally:
        connection.close()


@auth_bp.route("/admin/security/ip", methods=["POST"])
@admin_required
def update_ip_security():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    ip = (request.form.get("ip_address") or "").strip()[:100]
    action = request.form.get("action")
    note = (request.form.get("note") or "").strip()[:300]
    if not ip:
        return redirect(url_for("auth.user_management", success="IP 주소를 입력해주세요."))
    connection = dashboard_db()
    try:
        now_iso = now_kst().isoformat()
        if action == "unblock":
            connection.execute(
                """
                INSERT INTO login_ip_security
                    (ip_address, failed_attempts, unblocked_at, note, updated_at)
                VALUES (?, 0, ?, ?, ?)
                ON CONFLICT(ip_address) DO UPDATE SET
                    failed_attempts=0, first_failed_at=NULL, last_failed_at=NULL,
                    blocked_at=NULL, blocked_by=NULL, unblocked_at=excluded.unblocked_at,
                    note=excluded.note, updated_at=excluded.updated_at
                """,
                (ip, now_iso, note, now_iso),
            )
            message = f"{ip} 차단을 해제했습니다."
        elif action == "block":
            connection.execute(
                """
                INSERT INTO login_ip_security
                    (ip_address, failed_attempts, blocked_at, blocked_by, note, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(ip_address) DO UPDATE SET
                    failed_attempts=excluded.failed_attempts,
                    blocked_at=excluded.blocked_at, blocked_by=excluded.blocked_by,
                    note=excluded.note, updated_at=excluded.updated_at
                """,
                (
                    ip, LOGIN_IP_MAX_FAILURES, now_iso,
                    session.get("username") or "admin", note, now_iso,
                ),
            )
            message = f"{ip}를 차단했습니다."
        elif action == "note":
            connection.execute(
                "UPDATE login_ip_security SET note=?, updated_at=? WHERE ip_address=?",
                (note, now_iso, ip),
            )
            message = f"{ip} 메모를 저장했습니다."
        else:
            abort(400)
        connection.commit()
        return redirect(url_for("auth.user_management", success=message))
    finally:
        connection.close()

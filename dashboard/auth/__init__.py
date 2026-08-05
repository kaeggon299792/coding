"""
로그인/로그아웃, 세션 인증, CSRF 보호.

기존 portfolio/app.py의 세션 쿠키 설정(HttpOnly/Secure/SameSite=Lax)과 로그인
시도 제한 패턴을 참고하되, 비밀번호는 평문 비교가 아니라 werkzeug의 해시로
저장/검증한다(스펙이 명시적으로 해시 저장을 요구함).
"""

import secrets
import html
import json
import re
import sqlite3
import hashlib
import uuid
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, g, jsonify, make_response, redirect, render_template, request, session, url_for
from authlib.integrations.flask_client import OAuth
from authlib.integrations.base_client.errors import OAuthError
from werkzeug.security import check_password_hash, generate_password_hash

from dashboard_db import queries
from extensions import dashboard_db
from services import (
    ai_insights, ai_runtime_settings, gemini_usage, localization_auto_translation,
    localization_management,
    security_audit, site_preferences, task_registry, telegram_alert,
)
import config
from utils import now_kst

auth_bp = Blueprint("auth", __name__)
oauth = OAuth()

LOGIN_IP_MAX_FAILURES = 10
SESSION_IDLE_TIMEOUT = timedelta(minutes=config.SESSION_IDLE_MINUTES)
SESSION_ABSOLUTE_TIMEOUT = timedelta(hours=config.SESSION_ABSOLUTE_HOURS)
REMEMBER_COOKIE_NAME = "casino_in_remember"
REGISTRATION_AUTO_APPROVAL_KEY = "registration_auto_approval"
def _profile_image_suffix(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return ".webp"
    return None

MENU_PERMISSIONS = {
    "bug_reports": "버그 및 건의",
    "disclosures": "기업별 공시",
    "laws": "법률·규제",
    "companies": "기업정보",
    "research_library": "기업별 리포트",
    "official_docs": "공문·자료관리",
    "unified_search": "통합검색",
    "tips": "자료실",
}
LANDING_ENDPOINTS = {
    "dashboard": "dashboard_home",
    "bug_reports": "action_items_page",
    "performance": "market_trend_page",
    "disclosures": "disclosures_page",
    "laws": "laws_page",
    "companies": "companies_page",
    "research_library": "research_library_page",
    "official_docs": "official_docs.dashboard",
    "unified_search": "unified_search_page",
    "tips": "tips.list_page",
}


def init_oauth(app):
    """Attach Google OIDC to the existing Flask app without creating another app."""

    oauth.init_app(app)
    oauth.register(
        name="google",
        client_id=config.GOOGLE_CLIENT_ID or None,
        client_secret=config.GOOGLE_CLIENT_SECRET or None,
        server_metadata_url=config.GOOGLE_OIDC_METADATA_URL,
        client_kwargs={"scope": "openid email profile"},
    )
    missing = google_oauth_missing_settings()
    if missing:
        app.logger.warning(
            "Google OAuth is disabled; missing environment variables: %s",
            ", ".join(missing),
        )


def google_oauth_missing_settings():
    settings = {
        "GOOGLE_CLIENT_ID": config.GOOGLE_CLIENT_ID,
        "GOOGLE_CLIENT_SECRET": config.GOOGLE_CLIENT_SECRET,
        "GOOGLE_REDIRECT_URI": config.GOOGLE_REDIRECT_URI,
    }
    return [name for name, value in settings.items() if not value]


def current_menu_permissions():
    cached = getattr(g, "current_menu_permissions", None)
    if cached is not None:
        return cached
    if not session.get("user_id"):
        permissions = {code: False for code in MENU_PERMISSIONS}
        g.current_menu_permissions = permissions
        return permissions
    connection = None
    try:
        user = getattr(g, "current_user_record", None)
        if user is None:
            connection = dashboard_db()
            user = connection.execute(
                "SELECT role, is_active FROM dashboard_users WHERE id=?",
                (session["user_id"],),
            ).fetchone()
        if user and user["is_active"]:
            session["role"] = user["role"] or "user"
            if session["role"] == "admin":
                permissions = {code: True for code in MENU_PERMISSIONS}
                g.current_menu_permissions = permissions
                return permissions
        elif not (current_app.testing and not user):
            permissions = {code: False for code in MENU_PERMISSIONS}
            g.current_menu_permissions = permissions
            return permissions
        if connection is None:
            connection = dashboard_db()
        permissions = queries.get_user_permissions(
            connection, session["user_id"], MENU_PERMISSIONS.keys()
        )
        g.current_menu_permissions = permissions
        return permissions
    finally:
        if connection is not None:
            connection.close()


def _client_ip():
    # PythonAnywhere supplies the real client address to Flask as remote_addr.
    return (request.remote_addr or "unknown").strip()[:100]


def _ip_security_row(connection, ip):
    row = connection.execute(
        "SELECT * FROM login_ip_security WHERE ip_address=?", (ip,)
    ).fetchone()
    return dict(row) if row else None


def _user_ip_history(connection, user_ids):
    """Return recent signup/login IPs grouped by account without N+1 queries."""
    user_ids = [int(user_id) for user_id in user_ids]
    if not user_ids:
        return {}
    placeholders = ",".join("?" for _ in user_ids)
    rows = connection.execute(
        f"""
        SELECT seen.user_id, seen.ip_address, MAX(seen.seen_at) AS last_seen_at,
               MAX(CASE WHEN security.blocked_at IS NOT NULL THEN 1 ELSE 0 END) AS is_blocked
        FROM (
            SELECT user_id, ip_address, created_at AS seen_at
            FROM security_audit_log
            WHERE user_id IN ({placeholders})
              AND action IN ('LOGIN_SUCCESS', 'GOOGLE_LOGIN_SUCCESS')
            UNION ALL
            SELECT CAST(resource_id AS INTEGER), ip_address, created_at
            FROM security_audit_log
            WHERE action='SELF_REGISTRATION'
              AND CAST(resource_id AS INTEGER) IN ({placeholders})
            UNION ALL
            SELECT user_id, ip_address, last_seen_at
            FROM dashboard_active_sessions
            WHERE user_id IN ({placeholders})
        ) AS seen
        LEFT JOIN login_ip_security AS security ON security.ip_address=seen.ip_address
        WHERE seen.ip_address IS NOT NULL AND TRIM(seen.ip_address)<>''
              AND seen.ip_address<>'unknown'
        GROUP BY seen.user_id, seen.ip_address
        ORDER BY seen.user_id, last_seen_at DESC
        """,
        (*user_ids, *user_ids, *user_ids),
    ).fetchall()
    grouped = {user_id: [] for user_id in user_ids}
    for row in rows:
        user_id = int(row["user_id"])
        if len(grouped.setdefault(user_id, [])) < 5:
            grouped[user_id].append(dict(row))
    return grouped


def _user_has_recorded_ip(connection, user_id, ip_address):
    return any(
        item["ip_address"] == ip_address
        for item in _user_ip_history(connection, [user_id]).get(user_id, [])
    )


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


def _remember_hash(raw_token):
    return hashlib.sha256(str(raw_token or "").encode("utf-8")).hexdigest()


def _issue_remember_token(connection, user_id):
    selector = secrets.token_hex(12)
    raw_token = secrets.token_urlsafe(32)
    now = now_kst()
    connection.execute(
        """INSERT INTO remember_login_tokens
           (selector, token_hash, user_id, created_at, expires_at, last_used_at,
            user_agent, ip_address)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (selector, _remember_hash(raw_token), user_id, now.isoformat(),
         (now + timedelta(days=config.REMEMBER_LOGIN_DAYS)).isoformat(),
         now.isoformat(), str(request.user_agent.string or "")[:500], _client_ip()),
    )
    return f"{selector}.{raw_token}"


def _revoke_remember_cookie(connection, cookie_value, reason="revoked"):
    selector = str(cookie_value or "").partition(".")[0]
    if selector:
        connection.execute(
            "UPDATE remember_login_tokens SET revoked_at=? WHERE selector=? AND revoked_at IS NULL",
            (now_kst().isoformat(), selector),
        )


def _revoke_user_remember_tokens(connection, user_id):
    connection.execute(
        "UPDATE remember_login_tokens SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
        (now_kst().isoformat(), user_id),
    )


def restore_remembered_login():
    """Restore a normal server-side session from a hashed long-lived token."""
    if session.get("user_id"):
        return False
    cookie_value = request.cookies.get(REMEMBER_COOKIE_NAME, "")
    selector, separator, raw_token = cookie_value.partition(".")
    if not separator or not selector or not raw_token:
        return False
    connection = dashboard_db()
    try:
        ip_status = _ip_security_row(connection, _client_ip())
        if ip_status and ip_status.get("blocked_at"):
            g.clear_remember_cookie = True
            return False
        row = connection.execute(
            """SELECT t.selector, t.token_hash, t.expires_at, t.revoked_at,
                      u.id AS user_id, u.username, u.role, u.is_active
               FROM remember_login_tokens t
               JOIN dashboard_users u ON u.id=t.user_id
               WHERE t.selector=?""",
            (selector,),
        ).fetchone()
        if not row:
            g.clear_remember_cookie = True
            return False
        item = dict(row)
        try:
            valid_time = now_kst() < datetime.fromisoformat(item["expires_at"])
        except (TypeError, ValueError):
            valid_time = False
        valid = (
            not item.get("revoked_at") and valid_time and item.get("is_active")
            and secrets.compare_digest(item["token_hash"], _remember_hash(raw_token))
        )
        if not valid:
            _revoke_remember_cookie(connection, cookie_value, "invalid")
            connection.commit()
            g.clear_remember_cookie = True
            return False
        user = {
            "id": item["user_id"], "username": item["username"],
            "role": item.get("role") or "user",
        }
        _start_user_session(connection, user)
        # A remember token is single-use. Rotate it after successful restoration
        # so a copied cookie cannot be replayed for the remainder of its lifetime.
        _revoke_remember_cookie(connection, cookie_value, "rotated_after_use")
        g.remember_cookie_value = _issue_remember_token(connection, user["id"])
        queries.touch_last_login(connection, user["id"])
        security_audit.log_event(
            connection, "REMEMBER_LOGIN_SUCCESS", "dashboard_user", user["id"]
        )
        connection.commit()
        return True
    finally:
        connection.close()


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


def refresh_current_session():
    """Validate and refresh the signed-in session before any route reads it.

    Public pages may still contain private, role-gated panels for signed-in
    users.  Therefore session expiry and revocation must be enforced before
    those route functions run, not only inside ``login_required``.
    """

    if getattr(g, "current_session_checked", False):
        return bool(session.get("user_id"))
    g.current_session_checked = True
    if not session.get("user_id"):
        return False

    connection = dashboard_db()
    try:
        user = connection.execute(
            """
            SELECT id, username, role, name, picture_url, approval_status,
                   is_active, password_changed_at
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
            g.session_expired = True
            return False
        if user:
            g.current_user_record = dict(user)
            session["username"] = user["username"]
            session["role"] = user["role"] or "user"
        connection.commit()
        return True
    finally:
        connection.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                message = "세션이 만료되었습니다." if getattr(
                    g, "session_expired", False
                ) else "로그인이 필요합니다."
                return jsonify({"success": False, "message": message}), 401
            if getattr(g, "session_expired", False):
                return redirect(
                    url_for(
                        "auth.login",
                        expired="1",
                        next=f"{request.script_root}{request.full_path.rstrip('?')}",
                    )
                )
            return redirect(
                url_for(
                    "auth.login",
                    next=f"{request.script_root}{request.full_path.rstrip('?')}",
                )
            )
        if not refresh_current_session():
            if request.path.startswith("/api/"):
                return jsonify({"success": False, "message": "세션이 만료되었습니다."}), 401
            return redirect(
                url_for(
                    "auth.login",
                    expired="1",
                    next=f"{request.script_root}{request.full_path.rstrip('?')}",
                )
            )
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


def _safe_local_next(value):
    """Return a same-origin path and preserve the active locale prefix."""

    if not value:
        return None
    parsed = urlsplit(str(value))
    if (
        parsed.scheme
        or parsed.netloc
        or not parsed.path.startswith("/")
        or parsed.path.startswith("//")
    ):
        return None
    path = parsed.path
    if request.script_root == "/en" and path != "/en" and not path.startswith("/en/"):
        path = f"/en{path}"
    if request.script_root != "/en" and (path == "/en" or path.startswith("/en/")):
        # An explicit English destination remains valid when submitted from Korean.
        pass
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{path}{query}"


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


def _unique_google_username(connection, email, google_sub):
    local_part = (email.split("@", 1)[0] if "@" in email else "").strip()
    candidate = re.sub(r"[^A-Za-z0-9._-]", "-", local_part)[:40].strip(".-_")
    if len(candidate) < 3:
        candidate = f"google-{google_sub[-12:]}"[:40]
    base = candidate
    suffix = 1
    while connection.execute(
        "SELECT 1 FROM dashboard_users WHERE LOWER(username)=LOWER(?)", (candidate,)
    ).fetchone():
        suffix += 1
        marker = f"-{suffix}"
        candidate = f"{base[:40-len(marker)]}{marker}"
    return candidate


def _registration_auto_approval_enabled(connection):
    """Return the registration policy; absence intentionally means auto approval."""

    row = connection.execute(
        "SELECT setting_value FROM site_settings WHERE setting_key=?",
        (REGISTRATION_AUTO_APPROVAL_KEY,),
    ).fetchone()
    if row is None:
        return True
    return str(row["setting_value"]).strip().lower() in {"1", "true", "yes", "on"}


def _set_registration_auto_approval(connection, enabled, actor_id):
    connection.execute(
        """INSERT INTO site_settings(setting_key,setting_value,updated_by,updated_at)
           VALUES (?,?,?,?)
           ON CONFLICT(setting_key) DO UPDATE SET
               setting_value=excluded.setting_value,
               updated_by=excluded.updated_by,
               updated_at=excluded.updated_at""",
        (
            REGISTRATION_AUTO_APPROVAL_KEY,
            "1" if enabled else "0",
            actor_id,
            now_kst().isoformat(),
        ),
    )


def _upsert_google_user(connection, userinfo):
    """Create, link, or refresh a Google user identified by the stable OIDC sub."""

    google_sub = str(userinfo["sub"]).strip()
    email = str(userinfo["email"]).strip().lower()
    name = str(userinfo.get("name") or "").strip()[:200] or None
    picture_url = str(userinfo.get("picture") or "").strip()[:1000] or None
    now_iso = now_kst().isoformat()

    row = connection.execute(
        "SELECT * FROM dashboard_users WHERE google_sub=?", (google_sub,)
    ).fetchone()
    linked_existing_account = False
    created = False

    if row is None:
        email_row = connection.execute(
            "SELECT * FROM dashboard_users WHERE LOWER(email)=LOWER(?)", (email,)
        ).fetchone()
        if email_row is not None:
            if email_row["google_sub"] and email_row["google_sub"] != google_sub:
                raise ValueError("google_identity_conflict")
            row = email_row
            linked_existing_account = True

    if row is None:
        username = _unique_google_username(connection, email, google_sub)
        auto_approved = _registration_auto_approval_enabled(connection)
        unusable_password = generate_password_hash(
            secrets.token_urlsafe(48), method="scrypt"
        )
        cursor = connection.execute(
            """
            INSERT INTO dashboard_users
                (username, password_hash, role, is_active, created_at, updated_at,
                 landing_page, email, approval_status, google_sub, name, picture_url)
            VALUES (?, ?, 'user', ?, ?, ?, 'dashboard', ?, ?, ?, ?, ?)
            """,
            (
                username, unusable_password, 1 if auto_approved else 0,
                now_iso, now_iso, email,
                "approved" if auto_approved else "pending",
                google_sub, name, picture_url,
            ),
        )
        default_permissions = {"bug_reports", "disclosures", "laws", "companies"}
        queries.replace_user_permissions(
            connection,
            cursor.lastrowid,
            MENU_PERMISSIONS.keys(),
            default_permissions,
            None,
        )
        row = connection.execute(
            "SELECT * FROM dashboard_users WHERE id=?", (cursor.lastrowid,)
        ).fetchone()
        created = True
    else:
        conflicting_email = connection.execute(
            "SELECT id FROM dashboard_users WHERE LOWER(email)=LOWER(?) AND id<>?",
            (email, row["id"]),
        ).fetchone()
        email_to_store = row["email"] or (row["email"] if conflicting_email else email)
        name_to_store = row["name"] or name
        picture_to_store = row["picture_url"] or picture_url
        connection.execute(
            """
            UPDATE dashboard_users
            SET google_sub=?, email=?, name=?, picture_url=?, updated_at=?
            WHERE id=?
            """,
            (google_sub, email_to_store, name_to_store, picture_to_store, now_iso, row["id"]),
        )
        row = connection.execute(
            "SELECT * FROM dashboard_users WHERE id=?", (row["id"],)
        ).fetchone()

    return dict(row), created, linked_existing_account


def _send_registration_review_alert(
    user_id, username, email, provider="local", *, auto_approved=False
):
    review_path = url_for("auth.user_management", pending_user=user_id)
    review_url = (
        f"{config.DASHBOARD_PUBLIC_URL.rstrip('/')}{review_path}#user-{user_id}"
    )
    provider_label = "Google" if provider == "google" else "아이디·비밀번호"
    alert_message = (
        "👤 <b>CASINO IN 가입 신청</b>\n\n"
        f"• 아이디: {html.escape(username)}\n"
        f"• 이메일: {html.escape(email)}\n"
        f"• 가입 방식: {provider_label}\n"
        f"• 신청 시각: {now_kst().strftime('%Y-%m-%d %H:%M:%S KST')}\n"
        f"• 상태: {'자동 승인 완료' if auto_approved else '관리자 승인 대기'}\n\n"
        f'<a href="{html.escape(review_url, quote=True)}">'
        f"{'가입 계정 확인' if auto_approved else '가입 신청 검토·승인'}</a>\n"
        + (
            "※ 자동 가입승인 정책에 따라 즉시 활성화됐습니다."
            if auto_approved
            else "※ 관리자 로그인 후 검토 화면이 열리며, 실제 승인은 CSRF 보호 버튼으로 처리됩니다."
        )
    )
    if not telegram_alert.send_alert(alert_message, force=True):
        current_app.logger.error(
            "가입 신청 텔레그램 알림 전송 실패 user_id=%s provider=%s",
            user_id,
            provider,
        )


def _google_login_error(message, status=400):
    return render_template(
        "login.html",
        csrf_token=get_csrf_token(),
        error=message,
        notice=None,
    ), status


@auth_bp.route("/login/google")
def google_login():
    missing = google_oauth_missing_settings()
    if missing:
        current_app.logger.error(
            "Google OAuth login unavailable; missing settings: %s", ", ".join(missing)
        )
        return _google_login_error(
            "Google 로그인을 현재 사용할 수 없습니다. 관리자에게 문의해주세요.", 503
        )
    next_path = _safe_local_next(request.args.get("next"))
    if next_path:
        session["oauth_next"] = next_path
    else:
        session.pop("oauth_next", None)
    try:
        return oauth.google.authorize_redirect(config.GOOGLE_REDIRECT_URI)
    except Exception as exc:
        current_app.logger.error(
            "Google OAuth authorization start failed type=%s", type(exc).__name__
        )
        return _google_login_error(
            "Google 로그인 요청을 시작하지 못했습니다. 잠시 후 다시 시도해주세요.", 503
        )


@auth_bp.route("/auth/google/callback")
def google_callback():
    if request.args.get("error"):
        failure = "cancelled" if request.args.get("error") == "access_denied" else "provider_error"
        current_app.logger.warning("Google OAuth callback failed type=%s", failure)
        return _google_login_error(
            "Google 로그인이 취소되었습니다. 다시 시도하거나 다른 로그인 방법을 이용해주세요."
            if failure == "cancelled"
            else "Google 인증을 완료하지 못했습니다. 잠시 후 다시 시도해주세요."
        )

    if google_oauth_missing_settings():
        current_app.logger.error("Google OAuth callback failed type=missing_configuration")
        return _google_login_error(
            "Google 로그인 설정을 확인할 수 없습니다. 관리자에게 문의해주세요.", 503
        )

    try:
        token = oauth.google.authorize_access_token()
        userinfo = token.get("userinfo") if isinstance(token, dict) else None
    except OAuthError as exc:
        failure = getattr(exc, "error", None) or "oauth_state_or_token_error"
        current_app.logger.warning("Google OAuth callback failed type=%s", failure)
        return _google_login_error(
            "인증 요청이 만료되었거나 일치하지 않습니다. Google 로그인을 다시 시작해주세요."
        )
    except Exception as exc:
        current_app.logger.error(
            "Google OAuth callback failed type=%s", type(exc).__name__
        )
        return _google_login_error(
            "Google 인증 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        )

    if not isinstance(userinfo, dict):
        current_app.logger.warning("Google OAuth callback failed type=missing_userinfo")
        return _google_login_error("Google 계정 정보를 확인할 수 없습니다.")
    if not str(userinfo.get("sub") or "").strip():
        current_app.logger.warning("Google OAuth callback failed type=missing_sub")
        return _google_login_error("Google 계정 식별 정보를 확인할 수 없습니다.")
    if not str(userinfo.get("email") or "").strip():
        current_app.logger.warning("Google OAuth callback failed type=missing_email")
        return _google_login_error("Google 계정 이메일을 확인할 수 없습니다.")
    verified = userinfo.get("email_verified")
    if verified is not True and str(verified).lower() != "true":
        current_app.logger.warning("Google OAuth callback failed type=email_not_verified")
        return _google_login_error("이메일 인증이 완료된 Google 계정만 사용할 수 있습니다.", 403)

    next_path = _safe_local_next(session.get("oauth_next"))
    connection = dashboard_db()
    try:
        user, created, linked = _upsert_google_user(connection, userinfo)
        if created:
            auto_approved = user.get("approval_status") == "approved"
            security_audit.log_event(
                connection,
                (
                    "GOOGLE_REGISTRATION_AUTO_APPROVED"
                    if auto_approved
                    else "GOOGLE_REGISTRATION_PENDING"
                ),
                "dashboard_user",
                user["id"],
                {
                    "username": user["username"],
                    "approval_status": user["approval_status"],
                },
            )
            connection.commit()
            _send_registration_review_alert(
                user["id"], user["username"], user["email"], provider="google",
                auto_approved=auto_approved,
            )
            if not auto_approved:
                return _google_login_error(
                    "가입 신청이 접수되었습니다. 관리자가 승인하면 Google 계정으로 로그인할 수 있습니다.",
                    403,
                )
        if not user.get("is_active", 1) or user.get("approval_status") != "approved":
            connection.rollback()
            current_app.logger.warning(
                "Google OAuth callback failed type=account_inactive user_id=%s", user["id"]
            )
            return _google_login_error("사용이 중지된 계정입니다. 관리자에게 문의해주세요.", 403)
        landing_page = _landing_page_for_user(connection, user)
        _start_user_session(connection, user)
        queries.touch_last_login(connection, user["id"])
        security_audit.log_event(
            connection,
            "GOOGLE_LOGIN_SUCCESS",
            "dashboard_user",
            user["id"],
            {"created": created, "linked_existing_account": linked},
        )
        connection.commit()
        current_app.logger.info(
            "Google login succeeded user_id=%s at=%s", user["id"], now_kst().isoformat()
        )
    except (sqlite3.Error, ValueError) as exc:
        connection.rollback()
        current_app.logger.error(
            "Google OAuth user persistence failed type=%s", type(exc).__name__
        )
        return _google_login_error(
            "계정 정보를 저장하지 못했습니다. 관리자에게 문의해주세요.", 500
        )
    finally:
        connection.close()

    return redirect(
        next_path
        or url_for(LANDING_ENDPOINTS.get(landing_page, "dashboard_home"))
    )


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    values = {
        "username": (request.form.get("username") or "").strip(),
        "email": (request.form.get("email") or "").strip().lower(),
    }
    if request.method in {"GET", "HEAD"}:
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
        auto_approved = _registration_auto_approval_enabled(connection)
        cursor = connection.execute(
            """
            INSERT INTO dashboard_users
                (username, email, password_hash, role, is_active, created_at,
                 updated_at, password_changed_at, landing_page, approval_status)
            VALUES (?, ?, ?, 'user', ?, ?, ?, ?, 'dashboard', ?)
            """,
            (
                username, email, generate_password_hash(password, method="scrypt"),
                1 if auto_approved else 0,
                now_iso, now_iso, now_iso,
                "approved" if auto_approved else "pending",
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
            {
                "username": username,
                "approval_status": "approved" if auto_approved else "pending",
                "automatic_approval": auto_approved,
            },
        )
        connection.commit()
        _send_registration_review_alert(
            cursor.lastrowid, username, email, provider="local",
            auto_approved=auto_approved,
        )
        return redirect(url_for(
            "auth.login", registered="approved" if auto_approved else "1"
        ))
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
    if request.method in {"GET", "HEAD"}:
        return render_template(
            "login.html",
            csrf_token=get_csrf_token(),
            error=(
                "보안을 위해 로그인 세션이 종료되었습니다. 다시 로그인해주세요."
                if request.args.get("expired") == "1" else None
            ),
            notice=(
                "탈퇴 신청이 완료되었습니다. 계정 정보는 14일간 보관되며, 기간 내 복구는 관리자에게 요청할 수 있습니다."
                if request.args.get("withdrawn") == "1"
                else "비밀번호를 변경했습니다. 새 비밀번호로 다시 로그인해주세요."
                if request.args.get("password_changed") == "1"
                else "가입 신청이 접수되었습니다. 관리자가 승인하면 로그인할 수 있습니다."
                if request.args.get("registered") == "1"
                else "가입과 자동 승인이 완료되었습니다. 지금 로그인할 수 있습니다."
                if request.args.get("registered") == "approved"
                else None
            ),
        )

    submitted_token = request.form.get("csrf_token", "")
    if not validate_csrf(submitted_token):
        return render_template(
            "login.html", csrf_token=get_csrf_token(), error="요청이 만료되었습니다. 다시 시도해주세요."
        ), 400

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    remember_me = request.form.get("remember_me") == "1"

    ip = _client_ip()
    landing_page = "dashboard"
    connection = dashboard_db()
    remember_cookie = None
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
        if remember_me:
            remember_cookie = _issue_remember_token(connection, user["id"])
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

    next_path = _safe_local_next(request.args.get("next")) or url_for(
        LANDING_ENDPOINTS.get(landing_page, "dashboard_home")
    )
    response = make_response(redirect(next_path))
    if remember_cookie:
        response.set_cookie(
            REMEMBER_COOKIE_NAME, remember_cookie,
            max_age=config.REMEMBER_LOGIN_DAYS * 86400,
            secure=True, httponly=True, samesite="Lax", path="/",
        )
    return response


@auth_bp.route("/login/<path:unsupported_variant>", methods=["GET", "POST"])
def reject_unsupported_login_variant(unsupported_variant):
    """Do not expose fallback authentication flows under the login namespace."""
    abort(404)


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
        _revoke_remember_cookie(
            connection, request.cookies.get(REMEMBER_COOKIE_NAME), "user_logout"
        )
        connection.commit()
    finally:
        connection.close()
    session.clear()
    response = make_response(redirect(url_for("public_home")))
    response.delete_cookie(
        REMEMBER_COOKIE_NAME, secure=True, httponly=True, samesite="Lax", path="/"
    )
    return response


@auth_bp.route("/account")
@login_required
def my_account():
    connection = dashboard_db()
    try:
        user = connection.execute(
            """
            SELECT id, username, email, name, picture_url, google_sub, role,
                   created_at, updated_at, last_login_at, approval_status,
                   deletion_requested_at, deletion_scheduled_at
            FROM dashboard_users WHERE id=?
            """,
            (session["user_id"],),
        ).fetchone()
        if not user:
            session.clear()
            return redirect(url_for("auth.login"))
        return render_template(
            "account.html",
            user=dict(user),
            csrf_token=get_csrf_token(),
            error=(request.args.get("error") or "").strip(),
            success=(request.args.get("success") or "").strip(),
        )
    finally:
        connection.close()


@auth_bp.post("/account/email")
@login_required
def update_account_email():
    if not validate_csrf(request.form.get("csrf_token", "")):
        return render_template("403.html"), 400
    email = (request.form.get("email") or "").strip().lower()
    if not re.fullmatch(r"[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{2,}", email):
        return redirect(url_for("auth.my_account", error="이메일 형식을 확인해주세요."))
    connection = dashboard_db()
    try:
        user = connection.execute(
            "SELECT password_hash, google_sub FROM dashboard_users WHERE id=?",
            (session["user_id"],),
        ).fetchone()
        if not user:
            session.clear()
            return redirect(url_for("auth.login"))
        current_password = request.form.get("current_password") or ""
        if not user["google_sub"] and not check_password_hash(user["password_hash"], current_password):
            return redirect(url_for("auth.my_account", error="현재 비밀번호가 올바르지 않습니다."))
        duplicate = connection.execute(
            "SELECT 1 FROM dashboard_users WHERE LOWER(email)=LOWER(?) AND id<>?",
            (email, session["user_id"]),
        ).fetchone()
        if duplicate:
            return redirect(url_for("auth.my_account", error="이미 사용 중인 이메일입니다."))
        connection.execute(
            "UPDATE dashboard_users SET email=?, updated_at=? WHERE id=?",
            (email, now_kst().isoformat(), session["user_id"]),
        )
        security_audit.log_event(
            connection, "ACCOUNT_EMAIL_UPDATED", "dashboard_user", session["user_id"]
        )
        connection.commit()
    finally:
        connection.close()
    return redirect(url_for("auth.my_account", success="이메일을 변경했습니다."))


@auth_bp.post("/account/password")
@login_required
def update_account_password():
    if not validate_csrf(request.form.get("csrf_token", "")):
        return render_template("403.html"), 400
    current_password = request.form.get("current_password") or ""
    new_password = request.form.get("new_password") or ""
    confirmation = request.form.get("new_password_confirmation") or ""
    if new_password != confirmation:
        return redirect(url_for("auth.my_account", error="새 비밀번호 확인이 일치하지 않습니다."))
    if not _valid_password(new_password):
        return redirect(url_for(
            "auth.my_account", error="비밀번호는 10자 이상이며 영문, 숫자, 특수문자를 포함해야 합니다."
        ))
    connection = dashboard_db()
    try:
        user = connection.execute(
            "SELECT id, password_hash, google_sub FROM dashboard_users WHERE id=?",
            (session["user_id"],),
        ).fetchone()
        if not user:
            session.clear()
            return redirect(url_for("auth.login"))
        if not user["google_sub"] and not check_password_hash(user["password_hash"], current_password):
            return redirect(url_for("auth.my_account", error="현재 비밀번호가 올바르지 않습니다."))
        timestamp = now_kst().isoformat()
        connection.execute(
            """UPDATE dashboard_users SET password_hash=?, password_changed_at=?, updated_at=?
               WHERE id=?""",
            (generate_password_hash(new_password, method="scrypt"), timestamp, timestamp, user["id"]),
        )
        _revoke_user_sessions(connection, user["id"], "password_changed")
        _revoke_user_remember_tokens(connection, user["id"])
        security_audit.log_event(
            connection, "ACCOUNT_PASSWORD_UPDATED", "dashboard_user", user["id"]
        )
        connection.commit()
    finally:
        connection.close()
    session.clear()
    response = make_response(redirect(url_for("auth.login", password_changed="1")))
    response.delete_cookie(
        REMEMBER_COOKIE_NAME, secure=True, httponly=True, samesite="Lax", path="/"
    )
    return response


@auth_bp.post("/account/picture")
@login_required
def update_account_picture():
    if not validate_csrf(request.form.get("csrf_token", "")):
        return render_template("403.html"), 400
    uploaded = request.files.get("picture")
    if not uploaded or not uploaded.filename:
        return redirect(url_for("auth.my_account", error="프로필 사진을 선택해주세요."))
    data = uploaded.read(config.PROFILE_IMAGE_MAX_BYTES + 1)
    if len(data) > config.PROFILE_IMAGE_MAX_BYTES:
        return redirect(url_for("auth.my_account", error="프로필 사진은 3MB 이하만 가능합니다."))
    suffix = _profile_image_suffix(data)
    if not suffix:
        return redirect(url_for("auth.my_account", error="PNG, JPG, WebP 이미지만 가능합니다."))
    upload_dir = Path(config.BASE_DIR) / "static" / "uploads" / "profiles"
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{session['user_id']}-{uuid.uuid4().hex}{suffix}"
    (upload_dir / filename).write_bytes(data)
    picture_url = f"/static/uploads/profiles/{filename}"
    connection = dashboard_db()
    try:
        connection.execute(
            "UPDATE dashboard_users SET picture_url=?, updated_at=? WHERE id=?",
            (picture_url, now_kst().isoformat(), session["user_id"]),
        )
        security_audit.log_event(
            connection, "ACCOUNT_PICTURE_UPDATED", "dashboard_user", session["user_id"]
        )
        connection.commit()
    finally:
        connection.close()
    return redirect(url_for("auth.my_account", success="프로필 사진을 변경했습니다."))


@auth_bp.route("/account/withdraw", methods=["POST"])
@login_required
def withdraw_account():
    if not validate_csrf(request.form.get("csrf_token", "")):
        return render_template("403.html"), 400
    if (request.form.get("confirmation") or "").strip() != "탈퇴":
        return redirect(url_for(
            "auth.my_account", error="확인란에 ‘탈퇴’를 정확히 입력해주세요."
        ))

    connection = dashboard_db()
    try:
        target = connection.execute(
            "SELECT id, username, role, approval_status FROM dashboard_users WHERE id=?",
            (session["user_id"],),
        ).fetchone()
        if not target:
            session.clear()
            return redirect(url_for("auth.login"))
        if target["role"] == "admin":
            return redirect(url_for(
                "auth.my_account",
                error="관리자 계정은 직접 탈퇴할 수 없습니다. 다른 관리자에게 권한 변경을 요청해주세요.",
            ))
        if target["approval_status"] == "withdrawal_pending":
            return redirect(url_for("auth.login", withdrawn="1"))

        now = now_kst()
        scheduled = now + timedelta(days=14)
        connection.execute(
            """
            UPDATE dashboard_users
            SET is_active=0, approval_status='withdrawal_pending',
                deletion_requested_at=?, deletion_scheduled_at=?, updated_at=?
            WHERE id=?
            """,
            (now.isoformat(), scheduled.isoformat(), now.isoformat(), target["id"]),
        )
        _audit_user(
            connection,
            target,
            "ACCOUNT_WITHDRAWAL_REQUESTED",
            {"retention_days": 14, "deletion_scheduled_at": scheduled.isoformat()},
        )
        _revoke_user_sessions(connection, target["id"], "account_withdrawal")
        _revoke_user_remember_tokens(connection, target["id"])
        connection.commit()
    finally:
        connection.close()
    session.clear()
    return redirect(url_for("auth.login", withdrawn="1"))


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
                       last_login_at, password_changed_at, landing_page,
                       deletion_requested_at, deletion_scheduled_at, deleted_at
                FROM dashboard_users ORDER BY is_active DESC, role, username
                """
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
        user_ip_history = _user_ip_history(
            connection,
            [user["id"] for user in users if user["approval_status"] != "deleted"],
        )
        return render_template(
            "user_management.html", users=users, error=error,
            success=success, csrf_token=get_csrf_token(),
            menu_permissions_catalog=MENU_PERMISSIONS,
            permission_matrix=permission_matrix,
            ip_security=ip_security,
            active_sessions=active_sessions,
            current_session_hash=(
                _session_hash(session.get("session_id")) if session.get("session_id") else None
            ),
            session_idle_minutes=config.SESSION_IDLE_MINUTES,
            session_absolute_hours=config.SESSION_ABSOLUTE_HOURS,
            login_ip_max_failures=LOGIN_IP_MAX_FAILURES,
            user_ip_history=user_ip_history,
            current_request_ip=_client_ip(),
            site_font=site_preferences.get_site_font(connection),
            site_font_choices=site_preferences.FONT_CHOICES,
            number_font=site_preferences.get_number_font(connection),
            number_font_choices=site_preferences.NUMBER_FONT_CHOICES,
            registration_auto_approval=_registration_auto_approval_enabled(connection),
        )
    finally:
        connection.close()


@auth_bp.post("/admin/site-settings/registration-approval")
@admin_required
def update_registration_approval_policy():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    mode = (request.form.get("approval_mode") or "").strip()
    if mode not in {"automatic", "manual"}:
        abort(400)
    enabled = mode == "automatic"
    connection = dashboard_db()
    try:
        _set_registration_auto_approval(
            connection, enabled, session.get("user_id")
        )
        security_audit.log_event(
            connection,
            "REGISTRATION_APPROVAL_POLICY_UPDATED",
            resource_type="site_settings",
            resource_id=REGISTRATION_AUTO_APPROVAL_KEY,
            detail={"automatic_approval": enabled},
        )
        connection.commit()
    finally:
        connection.close()
    return redirect(url_for(
        "auth.user_management",
        success=(
            "신규 가입을 자동 승인하도록 설정했습니다."
            if enabled
            else "신규 가입을 관리자 수동 승인으로 설정했습니다."
        ),
    ))


@auth_bp.get("/admin/ai-settings")
@admin_required
def ai_settings():
    connection = dashboard_db()
    try:
        openai_usage = queries.get_today_usage_summary(connection)
        openai_usage["call_limit"] = ai_insights.get_daily_call_limit(connection)
        return render_template(
            "ai_settings.html",
            success=request.args.get("success"),
            csrf_token=get_csrf_token(),
            openai_usage=openai_usage,
            ai_purpose_settings=ai_runtime_settings.dashboard(connection),
            gemini_usage=gemini_usage.admin_dashboard(connection),
        )
    finally:
        connection.close()


@auth_bp.post("/admin/ai-usage/limit")
@admin_required
def update_openai_call_limit():
    if not validate_csrf(request.form.get("csrf_token", "")):
        return render_template("403.html"), 400
    connection = dashboard_db()
    try:
        try:
            value = ai_insights.set_daily_call_limit(
                connection, request.form.get("call_limit"), session.get("user_id")
            )
        except ValueError as error:
            return redirect(url_for("auth.ai_settings", success=str(error)))
        security_audit.log_event(
            connection, "OPENAI_DAILY_LIMIT_UPDATED", resource_type="site_settings",
            resource_id="openai_daily_call_limit", detail={"call_limit": value},
        )
        connection.commit()
    finally:
        connection.close()
    return redirect(url_for(
        "auth.ai_settings", success=f"OpenAI 일일 호출 한도를 {value:,}회로 변경했습니다."
    ))


@auth_bp.post("/admin/ai-settings/purposes")
@admin_required
def update_ai_purpose_settings():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    saved = []
    try:
        try:
            for purpose in ai_runtime_settings.PURPOSES:
                prefix = f"{purpose}_"
                values = {
                    "enabled": request.form.get(f"{prefix}enabled"),
                    "model": request.form.get(f"{prefix}model"),
                    "daily_call_limit": request.form.get(f"{prefix}daily_call_limit"),
                }
                if purpose == "news_importance":
                    values.update({
                        "importance_threshold": request.form.get(
                            f"{prefix}importance_threshold"
                        ),
                        "web_importance_threshold": request.form.get(
                            f"{prefix}web_importance_threshold"
                        ),
                    })
                saved.append(ai_runtime_settings.save_purpose_settings(
                    connection, purpose, values, session.get("user_id")
                ))
        except ValueError as error:
            connection.rollback()
            return redirect(url_for("auth.ai_settings", success=str(error)))
        security_audit.log_event(
            connection,
            "AI_PURPOSE_SETTINGS_UPDATED",
            resource_type="site_settings",
            resource_id="ai_purpose",
            detail={
                item["purpose"]: {
                    "enabled": item["enabled"],
                    "model": item["model"],
                    "daily_call_limit": item["daily_call_limit"],
                    **({
                        "importance_threshold": item["importance_threshold"],
                        "web_importance_threshold": item["web_importance_threshold"],
                    } if item["purpose"] == "news_importance" else {}),
                }
                for item in saved
            },
        )
        connection.commit()
    finally:
        connection.close()
    return redirect(url_for(
        "auth.ai_settings", success="용도별 AI 설정을 저장했습니다."
    ))


@auth_bp.post("/admin/ai-usage/reset")
@admin_required
def reset_openai_daily_usage():
    if not validate_csrf(request.form.get("csrf_token", "")):
        return render_template("403.html"), 400
    connection = dashboard_db()
    try:
        previous = queries.get_today_usage_summary(connection)
        reset_at = ai_insights.reset_today_usage(connection, session.get("user_id"))
        security_audit.log_event(
            connection, "OPENAI_DAILY_USAGE_RESET", resource_type="api_usage",
            resource_id=now_kst().strftime("%Y-%m-%d"), detail={
                "previous_call_count": previous["call_count"],
                "previous_estimated_cost": previous["total_cost"],
                "reset_at": reset_at,
            },
        )
        connection.commit()
    finally:
        connection.close()
    return redirect(url_for(
        "auth.ai_settings", success="오늘 OpenAI 한도 카운터를 초기화했습니다. 기존 사용량 기록은 보존됩니다."
    ))


@auth_bp.get("/admin/logs")
@admin_required
def admin_logs():
    """Show account and security activity logs in independent 10-row pages."""

    page_size = 10
    account_page = max(1, request.args.get("account_page", 1, type=int))
    activity_page = max(1, request.args.get("activity_page", 1, type=int))
    api_page = max(1, request.args.get("api_page", 1, type=int))
    connection = dashboard_db()
    try:
        account_total = connection.execute(
            "SELECT COUNT(*) AS count FROM dashboard_user_audit"
        ).fetchone()["count"]
        activity_total = connection.execute(
            "SELECT COUNT(*) AS count FROM security_audit_log"
        ).fetchone()["count"]
        api_total = connection.execute(
            "SELECT COUNT(*) AS count FROM api_usage WHERE provider='openai' OR provider IS NULL"
        ).fetchone()["count"]

        account_pages = max(1, (account_total + page_size - 1) // page_size)
        activity_pages = max(1, (activity_total + page_size - 1) // page_size)
        api_pages = max(1, (api_total + page_size - 1) // page_size)
        account_page = min(account_page, account_pages)
        activity_page = min(activity_page, activity_pages)
        api_page = min(api_page, api_pages)

        audit = [
            dict(row)
            for row in connection.execute(
                """
                SELECT * FROM dashboard_user_audit
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (page_size, (account_page - 1) * page_size),
            ).fetchall()
        ]
        security_events = [
            dict(row)
            for row in connection.execute(
                """
                SELECT * FROM security_audit_log
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (page_size, (activity_page - 1) * page_size),
            ).fetchall()
        ]
        api_events = [
            dict(row)
            for row in connection.execute(
                """SELECT id,called_at,model,request_type,input_tokens,output_tokens,
                          estimated_cost,success,request_summary,response_summary,error_message
                   FROM api_usage
                   WHERE provider='openai' OR provider IS NULL
                   ORDER BY called_at DESC,id DESC LIMIT ? OFFSET ?""",
                (page_size, (api_page - 1) * page_size),
            ).fetchall()
        ]
        return render_template(
            "admin_logs.html",
            audit=audit,
            security_events=security_events,
            account_page=account_page,
            account_pages=account_pages,
            account_total=account_total,
            activity_page=activity_page,
            activity_pages=activity_pages,
            activity_total=activity_total,
            api_events=api_events,
            api_page=api_page,
            api_pages=api_pages,
            api_total=api_total,
        )
    finally:
        connection.close()


@auth_bp.get("/admin/tasks")
@admin_required
def admin_tasks():
    """Explain registered server/local tasks and show their latest evidence."""

    connection = dashboard_db()
    try:
        return render_template("admin_tasks.html", registry=task_registry.dashboard(connection))
    finally:
        connection.close()


@auth_bp.get("/admin/localization")
@admin_required
def localization_dashboard():
    page_size = 500
    configured_languages = localization_auto_translation.configured_languages()
    default_language = configured_languages[0] if configured_languages else "en"
    language_code = (request.args.get("language") or default_language).strip()
    query = (request.args.get("q") or "").strip()
    status = (
        (request.args.get("status") or "").strip()
        if "status" in request.args
        else "Pending"
    )
    priority = (request.args.get("priority") or "").strip()
    sort = (request.args.get("sort") or "newest").strip()
    try:
        page = max(1, int(request.args.get("page") or 1))
    except ValueError:
        page = 1
    connection = dashboard_db()
    try:
        languages = [dict(row) for row in connection.execute(
            "SELECT * FROM localization_languages WHERE is_active=1 ORDER BY is_source DESC, language_code"
        ).fetchall()]
        if language_code != "all" and (
            language_code not in {item["language_code"] for item in languages}
            or language_code == "ko"
        ):
            language_code = "en"
        if language_code == "all":
            summary = localization_management.dashboard_summary_all(connection)
            rows, total = localization_management.list_strings_all(
                connection, query=query, status=status, priority=priority,
                sort=sort, page=page, per_page=page_size,
            )
        else:
            summary = localization_management.dashboard_summary(connection, language_code)
            rows, total = localization_management.list_strings(
                connection, language_code=language_code, query=query, status=status,
                priority=priority, sort=sort, page=page, per_page=page_size,
            )
        language_names = {
            item["language_code"]: item["display_name"] for item in languages
        }
        for item in rows:
            item["target_language_code"] = item.get("target_language_code") or language_code
            item["target_language_name"] = (
                item.get("target_language_name")
                or language_names.get(item["target_language_code"], item["target_language_code"])
            )
            item["references"] = localization_management.references(connection, item["id"])
        glossary = (
            [] if language_code == "all"
            else localization_management.list_glossary(connection, language_code)
        )
        api_translation_languages = [
            language for language in languages
            if language["language_code"]
            in localization_auto_translation.configured_languages()
        ]
        return render_template(
            "localization_admin.html", summary=summary, items=rows, total=total,
            languages=languages, language_code=language_code, query=query,
            selected_status=status, selected_priority=priority, selected_sort=sort,
            page=page, pages=max(1, (total + page_size - 1) // page_size),
            csrf_token=get_csrf_token(), scan_result=request.args.get("scan"),
            import_result=request.args.get("imported"),
            glossary=glossary,
            api_translation_languages=api_translation_languages,
        )
    finally:
        connection.close()


@auth_bp.get("/admin/localization/work")
@admin_required
def localization_work():
    """Small, deterministic translation batches for an hourly browser workflow."""

    limit = 50
    language_code = (request.args.get("language") or "en").strip()
    connection = dashboard_db()
    try:
        languages = [dict(row) for row in connection.execute(
            """SELECT language_code, display_name
               FROM localization_languages
               WHERE is_active=1 AND is_source=0
               ORDER BY language_code"""
        ).fetchall()]
        language_codes = {item["language_code"] for item in languages}
        if language_code not in language_codes:
            language_code = languages[0]["language_code"] if languages else "en"
        rows, total = localization_management.list_strings(
            connection,
            language_code=language_code,
            status="Pending",
            sort="priority",
            page=1,
            per_page=limit,
        )
        chunks = []
        if rows:
            chunks = localization_management.generate_translation_chunks(
                connection,
                language_code,
                [row["id"] for row in rows],
                mode="prompt",
                style="casino",
                max_items=limit,
            )
        return render_template(
            "localization_work.html",
            languages=languages,
            language_code=language_code,
            limit=limit,
            allowed_limits=(limit,),
            total=total,
            batch_count=len(rows),
            chunks=chunks,
            csrf_token=get_csrf_token(),
            import_result=request.args.get("imported"),
            error=request.args.get("error"),
        )
    finally:
        connection.close()


@auth_bp.post("/admin/localization/<int:string_id>")
@admin_required
def localization_update(string_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    language_code = (request.form.get("language_code") or "en").strip()
    return_language_code = (
        request.form.get("return_language_code") or language_code
    ).strip()
    status = (request.form.get("status") or "Completed").strip()
    connection = dashboard_db()
    try:
        if not connection.execute(
            "SELECT 1 FROM localization_strings WHERE id=? AND deleted_at IS NULL", (string_id,)
        ).fetchone():
            abort(404)
        localization_management.save_translation(
            connection, string_id, language_code,
            request.form.get("translated_text") or "", session.get("user_id"), status=status,
        )
        connection.commit()
    except ValueError as exc:
        connection.rollback()
        return redirect(url_for("auth.localization_dashboard", language=return_language_code, error=str(exc)))
    finally:
        connection.close()
    return redirect(url_for("auth.localization_dashboard", language=return_language_code, saved="1"))


@auth_bp.post("/admin/localization/scan")
@admin_required
def localization_scan():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        project_root = Path(current_app.root_path)
        result = localization_management.scan_project(connection, project_root)
    finally:
        connection.close()
    return redirect(url_for(
        "auth.localization_dashboard",
        scan=f"{result['files_scanned']}개 파일 · {result['strings_seen']}개 문자열 확인",
    ))


@auth_bp.post("/admin/localization/api-translate")
@admin_required
def localization_api_translate():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    language_code = (request.form.get("language_code") or "").strip()
    connection = dashboard_db()
    try:
        try:
            result = localization_auto_translation.run_manual_batch(
                connection, Path(current_app.root_path), language_code,
                actor_id=session.get("user_id"),
            )
        except (ValueError, RuntimeError) as error:
            return redirect(url_for(
                "auth.localization_dashboard", language=language_code,
                error=str(error),
            ))
        security_audit.log_event(
            connection, "LOCALIZATION_API_TRANSLATION", "localization",
            language_code, detail={
                "pending": result["pending"], "saved": result["saved"],
                "rejected": result["rejected"], "remaining": result["remaining"],
            }, success=not bool(result["error"]),
        )
        connection.commit()
    finally:
        connection.close()
    if result["error"]:
        return redirect(url_for(
            "auth.localization_dashboard", language=language_code,
            error=result["error"],
        ))
    message = (
        f"API 번역 완료 · 대상 {result['pending']}건 · 저장 {result['saved']}건 · "
        f"검증 제외 {result['rejected']}건 · 남은 항목 {result['remaining']}건"
    )
    return redirect(url_for(
        "auth.localization_dashboard", language=language_code,
        api_result=message,
    ))


@auth_bp.get("/admin/localization/qa")
@admin_required
def localization_qa():
    language_code = (request.args.get("language") or "en").strip()
    connection = dashboard_db()
    try:
        findings = localization_management.qa_report(connection, language_code)
        return render_template(
            "localization_qa.html", findings=findings, language_code=language_code,
        )
    finally:
        connection.close()


@auth_bp.get("/admin/localization/export.<file_type>")
@admin_required
def localization_export(file_type):
    if file_type not in {"csv", "xlsx"}:
        abort(404)
    language_code = (request.args.get("language") or "en").strip()
    connection = dashboard_db()
    try:
        payload, mimetype = localization_management.export_file(
            connection, language_code, file_type,
        )
    finally:
        connection.close()
    response = make_response(payload)
    response.headers["Content-Type"] = mimetype
    response.headers["Content-Disposition"] = (
        f'attachment; filename="casino-in-localization-{language_code}.{file_type}"'
    )
    return response


@auth_bp.post("/admin/localization/import")
@admin_required
def localization_import():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    upload = request.files.get("file")
    if not upload or not upload.filename:
        abort(400)
    language_code = (request.form.get("language_code") or "en").strip()
    connection = dashboard_db()
    try:
        try:
            result = localization_management.import_file(
                connection, upload, language_code, session.get("user_id"),
            )
        except ValueError as exc:
            connection.rollback()
            return redirect(url_for("auth.localization_dashboard", error=str(exc)))
    finally:
        connection.close()
    return redirect(url_for(
        "auth.localization_dashboard", language=language_code,
        imported=f"{result['updated']}건 반영 · {result['errors']}건 제외",
    ))


@auth_bp.post("/admin/localization/prompt")
@admin_required
def localization_prompt():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    language_code = (request.form.get("language_code") or "en").strip()
    mode = (request.form.get("export_mode") or "prompt").strip()
    if mode not in {"data", "prompt"}:
        abort(400)
    style = (request.form.get("translation_style") or "natural").strip()
    connection = dashboard_db()
    try:
        try:
            if language_code == "all":
                chunks = localization_management.generate_all_translation_chunks(
                    connection, request.form.getlist("string_ids"),
                    mode=mode, style=style,
                )
            else:
                chunks = localization_management.generate_translation_chunks(
                    connection, language_code, request.form.getlist("string_ids"),
                    mode=mode, style=style,
                )
        except ValueError as exc:
            return redirect(url_for(
                "auth.localization_dashboard", language=language_code, error=str(exc)
            ))
        return render_template(
            "localization_prompt.html", chunks=chunks, language_code=language_code,
            return_language_code=(request.form.get("return_language_code") or "en"),
            mode=mode, style=style, csrf_token=get_csrf_token(),
        )
    finally:
        connection.close()


@auth_bp.post("/admin/localization/import-ai")
@admin_required
def localization_import_ai():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    language_code = (request.form.get("language_code") or "en").strip()
    translation_payload = request.form.get("translation_payload") or ""
    chunk_payloads = request.form.getlist("translation_chunk")
    if chunk_payloads:
        translation_payload = "\n\n".join(
            payload.strip() for payload in chunk_payloads if payload.strip()
        )
    connection = dashboard_db()
    try:
        try:
            detected_languages = localization_management.detect_ai_translation_languages(
                connection, translation_payload
            )
            if language_code == "all" or (
                detected_languages and detected_languages != {language_code}
            ):
                result = localization_management.import_ai_translation_text_all(
                    connection, translation_payload, session.get("user_id"),
                )
            else:
                result = localization_management.import_ai_translation_text(
                    connection, translation_payload,
                    language_code, session.get("user_id"),
                )
        except ValueError as exc:
            connection.rollback()
            if request.form.get("return_to") == "work" and language_code != "all":
                return redirect(url_for(
                    "auth.localization_work", language=language_code,
                    limit=50, error=str(exc),
                ))
            return redirect(url_for(
                "auth.localization_dashboard", language=language_code, error=str(exc)
            ))
    finally:
        connection.close()
    language_result = " · ".join(
        f"{code} {count}건"
        for code, count in (result.get("languages") or {}).items()
        if count
    )
    import_message = (
        f"AI 번역 {result['updated']}건 반영 · {result['errors']}건 제외"
        + (f" ({language_result})" if language_result else "")
    )
    if request.form.get("return_to") == "work" and language_code != "all":
        return redirect(url_for(
            "auth.localization_work", language=language_code, limit=50,
            imported=import_message,
        ))
    return redirect(url_for(
        "auth.localization_dashboard", language=("en" if language_code == "all" else language_code),
        imported=import_message,
    ))


@auth_bp.post("/admin/localization/glossary")
@admin_required
def localization_glossary_save():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    language_code = (request.form.get("language_code") or "en").strip()
    connection = dashboard_db()
    try:
        try:
            glossary_id = request.form.get("glossary_id")
            localization_management.save_glossary(
                connection, request.form.get("source_text"),
                request.form.get("target_text"), language_code,
                session.get("user_id"), int(glossary_id) if glossary_id else None,
            )
            connection.commit()
        except (TypeError, ValueError, sqlite3.IntegrityError) as exc:
            connection.rollback()
            return redirect(url_for(
                "auth.localization_dashboard", language=language_code, error=str(exc)
            ))
    finally:
        connection.close()
    return redirect(url_for("auth.localization_dashboard", language=language_code))


@auth_bp.post("/admin/localization/glossary/<int:glossary_id>/delete")
@admin_required
def localization_glossary_delete(glossary_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    language_code = (request.form.get("language_code") or "en").strip()
    connection = dashboard_db()
    try:
        try:
            localization_management.deactivate_glossary(
                connection, glossary_id, language_code
            )
            connection.commit()
        except ValueError as exc:
            connection.rollback()
            return redirect(url_for(
                "auth.localization_dashboard", language=language_code, error=str(exc)
            ))
    finally:
        connection.close()
    return redirect(url_for("auth.localization_dashboard", language=language_code))


@auth_bp.post("/admin/localization/languages")
@admin_required
def localization_add_language():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    language_code = (request.form.get("language_code") or "").strip()
    display_name = (request.form.get("display_name") or "").strip()
    if not re.fullmatch(r"[a-z]{2,3}(?:-[A-Z][A-Za-z0-9]{1,7})?", language_code):
        return redirect(url_for("auth.localization_dashboard", error="언어 코드를 확인해주세요."))
    if not display_name or len(display_name) > 80:
        return redirect(url_for("auth.localization_dashboard", error="언어 이름을 확인해주세요."))
    connection = dashboard_db()
    try:
        connection.execute(
            """INSERT INTO localization_languages
                   (language_code, display_name, is_source, is_active, created_at)
               VALUES (?, ?, 0, 1, ?)
               ON CONFLICT(language_code) DO UPDATE SET
                   display_name=excluded.display_name, is_active=1""",
            (language_code, display_name, now_kst().isoformat(timespec="seconds")),
        )
        connection.commit()
    finally:
        connection.close()
    return redirect(url_for("auth.localization_dashboard", language=language_code))


@auth_bp.post("/admin/site-settings/font")
@admin_required
def update_site_font():
    if not validate_csrf(request.form.get("csrf_token", "")):
        return render_template("403.html"), 400
    connection = dashboard_db()
    try:
        try:
            site_preferences.set_site_font(
                connection, request.form.get("site_font", ""), session.get("user_id")
            )
            site_preferences.set_number_font(
                connection, request.form.get("number_font", ""), session.get("user_id")
            )
        except ValueError as error:
            return redirect(url_for("auth.user_management", success=str(error)))
        security_audit.log_event(
            connection, "SITE_FONT_UPDATED", resource_type="site_settings",
            resource_id="site_font", detail={
                "site_font": request.form.get("site_font"),
                "number_font": request.form.get("number_font"),
            },
        )
        connection.commit()
    finally:
        connection.close()
    return redirect(url_for("auth.user_management", success="본문·숫자 글꼴을 변경했습니다."))


@auth_bp.route("/admin/users/<int:user_id>/restore-withdrawal", methods=["POST"])
@admin_required
def restore_withdrawn_user(user_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        return render_template("403.html"), 400
    connection = dashboard_db()
    try:
        target = connection.execute(
            """
            SELECT id, username, approval_status, deletion_scheduled_at
            FROM dashboard_users WHERE id=?
            """,
            (user_id,),
        ).fetchone()
        if not target or target["approval_status"] != "withdrawal_pending":
            return redirect(url_for("auth.user_management"))
        connection.execute(
            """
            UPDATE dashboard_users
            SET is_active=1, approval_status='approved', deletion_requested_at=NULL,
                deletion_scheduled_at=NULL, deleted_at=NULL, updated_at=?
            WHERE id=?
            """,
            (now_kst().isoformat(), user_id),
        )
        _audit_user(connection, target, "ACCOUNT_WITHDRAWAL_RESTORED")
        connection.commit()
        return redirect(url_for(
            "auth.user_management", success="탈퇴 신청을 취소하고 계정을 복구했습니다."
        ))
    finally:
        connection.close()


@auth_bp.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def schedule_user_deletion(user_id):
    """Disable another account now and anonymize it after the 14-day hold."""
    if not validate_csrf(request.form.get("csrf_token", "")):
        return render_template("403.html"), 400
    if user_id == session.get("user_id"):
        return redirect(url_for(
            "auth.user_management", success="현재 관리자 계정은 삭제할 수 없습니다."
        ))
    connection = dashboard_db()
    try:
        target = connection.execute(
            """
            SELECT id, username, role, is_active, approval_status, deletion_scheduled_at
            FROM dashboard_users WHERE id=?
            """,
            (user_id,),
        ).fetchone()
        if not target:
            return redirect(url_for("auth.user_management"))
        if target["approval_status"] == "deleted":
            return redirect(url_for(
                "auth.user_management", success="이미 삭제가 완료된 계정입니다."
            ))
        if target["approval_status"] == "withdrawal_pending":
            return redirect(url_for(
                "auth.user_management", success="이미 14일 삭제 대기 중인 계정입니다."
            ))
        if target["role"] == "admin" and target["is_active"]:
            active_admins = connection.execute(
                """
                SELECT COUNT(*) AS count FROM dashboard_users
                WHERE role='admin' AND is_active=1 AND approval_status<>'deleted'
                """
            ).fetchone()["count"]
            if active_admins <= 1:
                return redirect(url_for(
                    "auth.user_management", success="마지막 활성 관리자 계정은 삭제할 수 없습니다."
                ))
        now = now_kst()
        scheduled = now + timedelta(days=14)
        connection.execute(
            """
            UPDATE dashboard_users
            SET is_active=0, approval_status='withdrawal_pending',
                deletion_requested_at=?, deletion_scheduled_at=?, updated_at=?
            WHERE id=?
            """,
            (now.isoformat(), scheduled.isoformat(), now.isoformat(), user_id),
        )
        _audit_user(
            connection,
            target,
            "ACCOUNT_DELETION_SCHEDULED",
            {"retention_days": 14, "deletion_scheduled_at": scheduled.isoformat()},
        )
        _revoke_user_sessions(connection, user_id, "admin_account_deletion")
        connection.commit()
        return redirect(url_for(
            "auth.user_management",
            success=f"{target['username']} 계정을 비활성화했습니다. 14일 동안 복구할 수 있습니다.",
        ))
    finally:
        connection.close()


@auth_bp.route("/admin/users/<int:user_id>/delete-now", methods=["POST"])
@admin_required
def delete_user_immediately(user_id):
    """Immediately anonymize another account without the recovery hold."""
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    if user_id == session.get("user_id"):
        return redirect(url_for(
            "auth.user_management", success="현재 관리자 계정은 즉시 삭제할 수 없습니다."
        ))
    connection = dashboard_db()
    try:
        target = connection.execute(
            """
            SELECT id, username, role, is_active, approval_status
            FROM dashboard_users WHERE id=?
            """,
            (user_id,),
        ).fetchone()
        if not target or target["approval_status"] == "deleted":
            return redirect(url_for("auth.user_management"))
        if (request.form.get("confirmation") or "").strip() != target["username"]:
            return redirect(url_for(
                "auth.user_management", success="즉시 삭제 확인값이 일치하지 않습니다."
            ))
        if target["role"] == "admin" and target["is_active"]:
            active_admins = connection.execute(
                """
                SELECT COUNT(*) AS count FROM dashboard_users
                WHERE role='admin' AND is_active=1 AND approval_status<>'deleted'
                """
            ).fetchone()["count"]
            if active_admins <= 1:
                return redirect(url_for(
                    "auth.user_management",
                    success="마지막 활성 관리자 계정은 즉시 삭제할 수 없습니다.",
                ))
        now_iso = now_kst().isoformat()
        connection.execute(
            """
            UPDATE dashboard_users
            SET is_active=0, approval_status='withdrawal_pending',
                deletion_requested_at=COALESCE(deletion_requested_at, ?),
                deletion_scheduled_at=?, updated_at=?
            WHERE id=?
            """,
            (now_iso, now_iso, now_iso, user_id),
        )
        _audit_user(connection, target, "ACCOUNT_DELETION_IMMEDIATE")
        _revoke_user_sessions(connection, user_id, "admin_account_deletion_immediate")
        _revoke_user_remember_tokens(connection, user_id)
        connection.commit()
        queries.purge_expired_withdrawn_users(connection)
        return redirect(url_for(
            "auth.user_management",
            success=f"{target['username']} 계정의 개인정보를 즉시 삭제·익명화했습니다.",
        ))
    finally:
        connection.close()


@auth_bp.route("/admin/users/<int:user_id>/block-ip", methods=["POST"])
@admin_required
def block_user_ip(user_id):
    """Block a recorded signup/login IP for another account."""
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    ip = (request.form.get("ip_address") or "").strip()[:100]
    if user_id == session.get("user_id"):
        return redirect(url_for(
            "auth.user_management", success="현재 관리자 계정의 IP는 여기서 차단할 수 없습니다."
        ))
    if not ip:
        abort(400)
    if ip == _client_ip():
        return redirect(url_for(
            "auth.user_management", success="현재 접속 중인 관리자 IP는 차단할 수 없습니다."
        ))
    connection = dashboard_db()
    try:
        target = connection.execute(
            "SELECT id, username FROM dashboard_users WHERE id=?", (user_id,)
        ).fetchone()
        if not target or not _user_has_recorded_ip(connection, user_id, ip):
            abort(400)
        now_iso = now_kst().isoformat()
        note = f"{target['username']} 계정의 가입·로그인 기록에서 관리자 차단"
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
        _audit_user(connection, target, "ACCOUNT_IP_BLOCKED", {"ip_address": ip})
        connection.commit()
        return redirect(url_for(
            "auth.user_management", success=f"{ip}를 차단했습니다."
        ))
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
        if target["approval_status"] == "withdrawal_pending":
            return redirect(url_for(
                "auth.user_management", success="탈퇴 보관 중인 계정은 복구 버튼을 사용해주세요."
            ))
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

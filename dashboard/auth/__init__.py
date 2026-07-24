"""
로그인/로그아웃, 세션 인증, CSRF 보호.

기존 portfolio/app.py의 세션 쿠키 설정(HttpOnly/Secure/SameSite=Lax)과 로그인
시도 제한 패턴을 참고하되, 비밀번호는 평문 비교가 아니라 werkzeug의 해시로
저장/검증한다(스펙이 명시적으로 해시 저장을 요구함).
"""

import secrets
import time
from functools import wraps

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from dashboard_db import queries
from extensions import dashboard_db

auth_bp = Blueprint("auth", __name__)

LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 15 * 60
_login_attempts = {}


def _is_rate_limited(ip):
    now = time.time()
    attempts = [t for t in _login_attempts.get(ip, []) if now - t < LOGIN_WINDOW_SECONDS]
    _login_attempts[ip] = attempts
    return len(attempts) >= LOGIN_MAX_ATTEMPTS


def _record_failed_attempt(ip):
    _login_attempts.setdefault(ip, []).append(time.time())


def get_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


def validate_csrf(token):
    expected = session.get("csrf_token")
    return bool(expected) and bool(token) and secrets.compare_digest(expected, token)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify({"success": False, "message": "로그인이 필요합니다."}), 401
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", csrf_token=get_csrf_token())

    ip = request.remote_addr or "unknown"
    if _is_rate_limited(ip):
        return render_template(
            "login.html", csrf_token=get_csrf_token(), error="잠시 후 다시 시도해주세요."
        ), 429

    submitted_token = request.form.get("csrf_token", "")
    if not validate_csrf(submitted_token):
        return render_template(
            "login.html", csrf_token=get_csrf_token(), error="요청이 만료되었습니다. 다시 시도해주세요."
        ), 400

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    connection = dashboard_db()
    try:
        user = queries.get_user_by_username(connection, username)
        if not user or not check_password_hash(user["password_hash"], password):
            _record_failed_attempt(ip)
            return render_template(
                "login.html", csrf_token=get_csrf_token(), error="아이디 또는 비밀번호가 올바르지 않습니다."
            ), 401

        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session.permanent = True
        queries.touch_last_login(connection, user["id"])
    finally:
        connection.close()

    next_path = request.args.get("next") or url_for("dashboard_home")
    return redirect(next_path)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))

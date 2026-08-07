"""Member-only settings and the isolated Telegram assistant webhook."""

from __future__ import annotations

import hmac

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for

from auth import get_csrf_token, login_required, validate_csrf
from extensions import dashboard_db
from services import member_telegram


member_area_bp = Blueprint("member_area", __name__, url_prefix="/members")


@member_area_bp.get("/telegram")
@login_required
def telegram():
    connection = dashboard_db()
    try:
        state = member_telegram.status(connection, session["user_id"])
    finally:
        connection.close()
    return render_template(
        "member_telegram.html", telegram_state=state,
        telegram_configured=member_telegram.configured(), csrf_token=get_csrf_token(),
    )


@member_area_bp.post("/telegram/connect")
@login_required
def telegram_connect():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    if not member_telegram.configured():
        flash("Telegram 회원 알림이 아직 설정되지 않았습니다.", "error")
        return redirect(url_for("member_area.telegram"))
    connection = dashboard_db()
    try:
        deep_link = member_telegram.create_link(connection, session["user_id"])
    finally:
        connection.close()
    return redirect(deep_link)


@member_area_bp.post("/telegram/preferences")
@login_required
def telegram_preferences():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    preferences = {
        "comments": request.form.get("notify_comments") == "1",
        "news": request.form.get("notify_news") == "1",
        "recruitment": request.form.get("notify_recruitment") == "1",
    }
    connection = dashboard_db()
    try:
        saved = member_telegram.update_preferences(
            connection, session["user_id"], preferences
        )
    finally:
        connection.close()
    flash(
        "Telegram 알림 설정을 저장했습니다."
        if saved else "먼저 Telegram을 연결해주세요.",
        "success" if saved else "error",
    )
    return redirect(url_for("member_area.telegram"))


@member_area_bp.post("/telegram/disconnect")
@login_required
def telegram_disconnect():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        member_telegram.disconnect(connection, session["user_id"])
    finally:
        connection.close()
    flash("Telegram 연결을 해제했습니다.", "success")
    return redirect(url_for("member_area.telegram"))


@member_area_bp.post("/telegram/test")
@login_required
def telegram_test():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        sent = member_telegram.send_to_user(
            connection, session["user_id"], "CASINO IN 회원 알림 테스트입니다."
        )
    finally:
        connection.close()
    flash("테스트 메시지를 보냈습니다." if sent else "테스트 메시지를 보내지 못했습니다.",
          "success" if sent else "error")
    return redirect(url_for("member_area.telegram"))


@member_area_bp.post("/telegram/webhook")
def telegram_webhook():
    expected = member_telegram.webhook_secret()
    supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not expected or not hmac.compare_digest(expected, supplied):
        abort(403)
    payload = request.get_json(silent=True) or {}
    message = payload.get("message") or {}
    chat = message.get("chat") or {}
    text = str(message.get("text") or "").strip()
    parts = text.split(maxsplit=1)
    if not parts or parts[0] != "/start" or len(parts) != 2 or chat.get("type") != "private":
        return jsonify({"ok": True})
    connection = dashboard_db()
    try:
        linked = member_telegram.consume_link(
            connection, parts[1], chat.get("id"), (message.get("from") or {}).get("username"),
        )
    finally:
        connection.close()
    member_telegram.send_message(
        chat.get("id"),
        "CASINO IN 계정과 연결되었습니다." if linked else "연결 링크가 만료되었거나 이미 사용되었습니다.",
    )
    return jsonify({"ok": True})

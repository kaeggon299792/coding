"""Low-noise request anomaly logging and threshold alerts."""

from __future__ import annotations

import html
import json
import re
from datetime import timedelta

from flask import current_app, g, request

from services import security_audit, telegram_alert
from utils import now_kst


RULES = {
    "SECURITY_CSRF_FAILED": (3, 10, "CSRF 검증 실패", "정상 화면에서 발급한 보안 토큰이 없는 상태 변경 요청입니다."),
    "SECURITY_ACCESS_DENIED": (10, 10, "권한 없는 접근 반복", "로그인 또는 권한 검사에서 거부된 요청이 반복됐습니다."),
    "SECURITY_PATH_PROBE": (3, 10, "민감 경로 탐색", "공개되면 안 되는 설정·관리 파일 경로를 반복해서 찾았습니다."),
    "SECURITY_RATE_LIMITED": (3, 10, "호출 제한 반복", "동일 접속지에서 요청 제한을 여러 번 초과했습니다."),
}
ALERT_COOLDOWN_MINUTES = 60
SUSPICIOUS_PATH = re.compile(
    r"(?:^|/)(?:\.env|\.git|wp-admin|wp-login\.php|phpmyadmin|\.aws|\.ssh|server-status|config\.php)(?:/|$)",
    re.IGNORECASE,
)


def _classify(response):
    if getattr(g, "csrf_validation_failed", False):
        return "SECURITY_CSRF_FAILED"
    if response.status_code == 429:
        return "SECURITY_RATE_LIMITED"
    if response.status_code in {401, 403}:
        return "SECURITY_ACCESS_DENIED"
    if response.status_code in {400, 403, 404} and SUSPICIOUS_PATH.search(request.path):
        return "SECURITY_PATH_PROBE"
    return None


def should_inspect(response):
    return bool(_classify(response))


def inspect_response(connection, response):
    """Record a meaningful security event and alert only after its threshold."""
    action = _classify(response)
    if not action:
        return
    threshold, window_minutes, _title, explanation = RULES[action]
    ip_address = security_audit.client_ip()
    detail = {
        "method": request.method,
        "path": request.path[:500],
        "status_code": response.status_code,
        "threshold": threshold,
        "window_minutes": window_minutes,
        "explanation": explanation,
    }
    security_audit.log_event(
        connection, action, "request", request.path[:200], detail, success=False
    )

    now = now_kst()
    since = (now - timedelta(minutes=window_minutes)).isoformat(timespec="seconds")
    count = connection.execute(
        """SELECT COUNT(*) FROM security_audit_log
           WHERE action=? AND COALESCE(ip_address,'')=? AND created_at>=?""",
        (action, ip_address, since),
    ).fetchone()[0]
    if count < threshold:
        return

    fingerprint = f"{action}:{ip_address}"[:200]
    cooldown_since = (now - timedelta(minutes=ALERT_COOLDOWN_MINUTES)).isoformat(timespec="seconds")
    alerted = connection.execute(
        """SELECT 1 FROM security_audit_log
           WHERE action='SECURITY_THRESHOLD_ALERT' AND resource_id=? AND created_at>=?
           LIMIT 1""",
        (fingerprint, cooldown_since),
    ).fetchone()
    if alerted:
        return

    title = RULES[action][2]
    security_audit.log_event(
        connection,
        "SECURITY_THRESHOLD_ALERT",
        "security_rule",
        fingerprint,
        {**detail, "source_action": action, "event_count": count, "alert_cooldown_minutes": ALERT_COOLDOWN_MINUTES},
        success=False,
    )
    if current_app.config.get("TESTING"):
        return
    telegram_alert.send_alert(
        "\n".join([
            "🚨 <b>CASINO IN 보안 임계치 알림</b>",
            "",
            f"유형: {html.escape(title)}",
            f"설명: {html.escape(explanation)}",
            f"접속 IP: {html.escape(ip_address or '-')}",
            f"요청: {html.escape(request.method)} {html.escape(request.path[:300])}",
            f"최근 {window_minutes}분: {count}회 (기준 {threshold}회)",
            f"응답 상태: HTTP {response.status_code}",
            "",
            "관리자 → 로그의 보안 탐지 로그에서 상세 요청을 확인하세요.",
        ]),
        force=True,
    )


def describe_event(row):
    action = row.get("action") or ""
    if action == "SECURITY_THRESHOLD_ALERT":
        return "설정한 횟수를 넘어서 관리자 텔레그램 알림까지 발송된 보안 이벤트입니다."
    if action in RULES:
        return RULES[action][3]
    return ""


def parse_detail(row):
    try:
        value = json.loads(row.get("detail_json") or "{}")
    except (TypeError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}

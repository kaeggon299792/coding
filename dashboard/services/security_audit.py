"""Security-sensitive user activity audit logging."""

import json

from flask import has_request_context, request, session

from utils import now_kst


def client_ip():
    """Return the address supplied by the trusted PythonAnywhere proxy chain."""
    if not has_request_context():
        return ""
    # Forwarding headers are attacker-controlled when the origin hostname is
    # reached directly. PythonAnywhere already exposes the effective client as
    # remote_addr, matching the login-rate-limit implementation.
    return str(request.remote_addr or "")[:100]


def log_event(
    connection,
    action,
    resource_type=None,
    resource_id=None,
    detail=None,
    success=True,
):
    ip_address = client_ip() if has_request_context() else None
    user_agent = request.user_agent.string if has_request_context() else None
    connection.execute(
        """
        INSERT INTO security_audit_log
            (user_id, username, ip_address, user_agent, action, resource_type,
             resource_id, success, detail_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session.get("user_id") if has_request_context() else None,
            (session.get("username") or "anonymous") if has_request_context() else "system",
            str(ip_address or "")[:100] or None,
            str(user_agent or "")[:500] or None,
            str(action)[:100],
            str(resource_type or "")[:100] or None,
            str(resource_id or "")[:200] or None,
            int(bool(success)),
            json.dumps(detail or {}, ensure_ascii=False, default=str)[:10000],
            now_kst().isoformat(),
        ),
    )

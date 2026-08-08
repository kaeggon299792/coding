"""Member Telegram connections, isolated from the administrator alert bot."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

import requests

import config
from utils import now_kst


logger = logging.getLogger(__name__)
NOTIFICATION_TYPES = {
    "comments": {
        "column": "notify_comments", "label": "새 댓글 알림",
        "description": "내가 참여한 게시글에 새 댓글이 등록될 때",
    },
    "news": {
        "column": "notify_news", "label": "카지노 뉴스 소식",
        "description": "새 카지노 산업 뉴스 분석이 등록될 때",
    },
    "recruitment": {
        "column": "notify_recruitment", "label": "채용 소식",
        "description": "채용정보 게시판에 새 공고가 등록될 때",
    },
}
NOTIFICATION_PREFERENCES = {
    key: value["column"] for key, value in NOTIFICATION_TYPES.items()
}


def notification_options(state=None):
    state = state or {}
    return [
        {
            "key": key, "field": item["column"], "label": item["label"],
            "description": item["description"],
            "enabled": bool(state.get(item["column"], 1)),
        }
        for key, item in NOTIFICATION_TYPES.items()
    ]


def configured():
    return bool(config.TELEGRAM_MEMBER_BOT_TOKEN)


def _token_hash(raw_token):
    return hashlib.sha256(str(raw_token).encode("utf-8")).hexdigest()


def webhook_secret():
    if not configured():
        return ""
    return hmac.new(
        config.FLASK_SECRET_KEY.encode("utf-8"),
        config.TELEGRAM_MEMBER_BOT_TOKEN.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_link(connection, user_id, current=None):
    current = current or now_kst()
    raw_token = secrets.token_urlsafe(32)
    expires = current + timedelta(minutes=max(1, config.TELEGRAM_MEMBER_LINK_TTL_MINUTES))
    connection.execute(
        "DELETE FROM member_telegram_link_tokens WHERE user_id=? AND used_at IS NULL",
        (int(user_id),),
    )
    connection.execute(
        """INSERT INTO member_telegram_link_tokens
           (user_id,token_hash,expires_at,created_at) VALUES (?,?,?,?)""",
        (int(user_id), _token_hash(raw_token), expires.isoformat(timespec="seconds"),
         current.isoformat(timespec="seconds")),
    )
    connection.commit()
    username = config.TELEGRAM_MEMBER_BOT_USERNAME.lstrip("@")
    return f"https://t.me/{username}?start={raw_token}"


def consume_link(connection, raw_token, chat_id, telegram_username=None, current=None):
    """Consume a fresh site token and bind the Telegram chat to that account.

    A person can legitimately sign into a different CASINO IN account while
    using the same Telegram account.  The fresh, member-scoped one-time token
    proves control of the new site session, while the incoming update proves
    control of the Telegram chat.  Transfer that chat instead of leaving the
    new page permanently "not connected" behind a UNIQUE constraint.
    """
    current = current or now_kst()
    if not raw_token or not str(chat_id).lstrip("-").isdigit():
        return False
    row = connection.execute(
        """SELECT id,user_id,expires_at,used_at FROM member_telegram_link_tokens
           WHERE token_hash=?""",
        (_token_hash(raw_token),),
    ).fetchone()
    now_iso = current.isoformat(timespec="seconds")
    if not row or row["used_at"] or row["expires_at"] < now_iso:
        return False
    conflict = connection.execute(
        "SELECT user_id FROM member_telegram_connections WHERE telegram_chat_id=? AND user_id<>?",
        (str(chat_id), row["user_id"]),
    ).fetchone()
    if conflict:
        connection.execute(
            "DELETE FROM member_telegram_connections WHERE user_id=?",
            (conflict["user_id"],),
        )
    connection.execute(
        """INSERT INTO member_telegram_connections
           (user_id,telegram_chat_id,telegram_username,connected_at,updated_at,enabled)
           VALUES (?,?,?,?,?,1)
           ON CONFLICT(user_id) DO UPDATE SET telegram_chat_id=excluded.telegram_chat_id,
             telegram_username=excluded.telegram_username,connected_at=excluded.connected_at,
             updated_at=excluded.updated_at,enabled=1""",
        (row["user_id"], str(chat_id), (telegram_username or "")[:64] or None,
         now_iso, now_iso),
    )
    updated = connection.execute(
        "UPDATE member_telegram_link_tokens SET used_at=? WHERE id=? AND used_at IS NULL",
        (now_iso, row["id"]),
    )
    if not updated.rowcount:
        connection.rollback()
        return False
    connection.commit()
    return True


def status(connection, user_id):
    row = connection.execute(
        """SELECT telegram_username,connected_at,enabled,
                  notify_comments,notify_news,notify_recruitment
           FROM member_telegram_connections WHERE user_id=?""",
        (int(user_id),),
    ).fetchone()
    return dict(row) if row and int(row["enabled"] or 0) == 1 else None


def update_preferences(connection, user_id, preferences):
    values = {
        key: 1 if bool(preferences.get(key)) else 0
        for key in NOTIFICATION_PREFERENCES
    }
    updated = connection.execute(
        """UPDATE member_telegram_connections
           SET notify_comments=?,notify_news=?,notify_recruitment=?,updated_at=?
           WHERE user_id=? AND enabled=1""",
        (
            values["comments"], values["news"], values["recruitment"],
            now_kst().isoformat(timespec="seconds"), int(user_id),
        ),
    )
    connection.commit()
    return bool(updated.rowcount)


def disconnect(connection, user_id):
    connection.execute(
        "UPDATE member_telegram_connections SET enabled=0,updated_at=? WHERE user_id=?",
        (now_kst().isoformat(timespec="seconds"), int(user_id)),
    )
    connection.commit()


def send_message(chat_id, text):
    if not configured():
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_MEMBER_BOT_TOKEN}/sendMessage",
            json={"chat_id": str(chat_id), "text": str(text)[:4000]},
            timeout=min(15, config.TELEGRAM_REQUEST_TIMEOUT_SECONDS),
        )
        return response.ok and bool(response.json().get("ok"))
    except (requests.RequestException, ValueError):
        return False


def send_to_user(connection, user_id, text):
    row = connection.execute(
        """SELECT telegram_chat_id FROM member_telegram_connections
           WHERE user_id=? AND enabled=1""",
        (int(user_id),),
    ).fetchone()
    return bool(row) and send_message(row["telegram_chat_id"], text)


def broadcast(connection, preference, text, sender=None):
    """Send to active connected members who enabled one notification kind."""
    column = NOTIFICATION_PREFERENCES.get(str(preference))
    if not column:
        raise ValueError("지원하지 않는 Telegram 알림 종류입니다.")
    recipients = connection.execute(
        f"""SELECT c.telegram_chat_id
            FROM member_telegram_connections AS c
            JOIN dashboard_users AS u ON u.id=c.user_id
            WHERE c.enabled=1 AND c.{column}=1
              AND u.is_active=1 AND u.approval_status='approved'"""
    ).fetchall()
    send = sender or send_message
    sent = 0
    failed = 0
    for recipient in recipients:
        try:
            if send(recipient["telegram_chat_id"], text):
                sent += 1
            else:
                failed += 1
        except Exception:
            failed += 1
            logger.exception("Member Telegram broadcast failed preference=%s", preference)
    return {"recipients": len(recipients), "sent": sent, "failed": failed}

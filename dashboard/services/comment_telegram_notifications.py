"""Best-effort member Telegram notifications for comment conversations."""

from __future__ import annotations

import logging

from services import member_telegram
from utils import now_kst


logger = logging.getLogger(__name__)


def _excerpt(value, limit=180):
    compact = " ".join(str(value or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit].rstrip()}…"


def _message(*, post_title, comment_content, created_at, post_url):
    return (
        "💬 새 댓글 알림\n\n"
        f"게시글: {post_title}\n"
        f"새 댓글: {_excerpt(comment_content)}\n"
        f"작성 시간: {created_at}\n\n"
        f"게시글에서 확인 → {post_url}"
    )


def notify_new_comment(
    connection,
    *,
    scope_type,
    scope_id,
    author_id,
    comment_id,
    post_title,
    comment_content,
    created_at,
    post_url,
    sender=None,
):
    """Notify other connected participants immediately, without rate limiting.

    The author is subscribed before recipients are selected so their future
    comments participate in the same conversation. Delivery is deliberately
    best effort and never blocks the comment that has already been saved.
    """
    del comment_id  # Reserved for future delivery diagnostics without rate limiting.
    now_iso = now_kst().isoformat(timespec="seconds")
    try:
        connection.execute(
            """INSERT INTO comment_telegram_subscriptions
               (scope_type,scope_id,user_id,is_active,created_at,updated_at)
               VALUES (?,?,?,1,?,?)
               ON CONFLICT(scope_type,scope_id,user_id) DO UPDATE SET
                 is_active=1,updated_at=excluded.updated_at""",
            (str(scope_type), str(scope_id), int(author_id), now_iso, now_iso),
        )
        recipients = connection.execute(
            """SELECT c.telegram_chat_id
               FROM comment_telegram_subscriptions AS s
               JOIN member_telegram_connections AS c ON c.user_id=s.user_id
               JOIN dashboard_users AS u ON u.id=s.user_id
               WHERE s.scope_type=? AND s.scope_id=? AND s.is_active=1
                 AND c.enabled=1 AND c.notify_comments=1
                 AND u.is_active=1 AND u.approval_status='approved'
                 AND s.user_id<>?""",
            (str(scope_type), str(scope_id), int(author_id)),
        ).fetchall()
        connection.commit()
    except Exception:
        connection.rollback()
        logger.exception("Failed to prepare member comment Telegram notifications")
        return {"sent": 0, "failed": 0}

    send = sender or member_telegram.send_message
    text = _message(
        post_title=post_title,
        comment_content=comment_content,
        created_at=created_at,
        post_url=post_url,
    )
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
            logger.exception("Member comment Telegram notification failed")
    return {"sent": sent, "failed": failed}

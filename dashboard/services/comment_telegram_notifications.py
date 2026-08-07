"""Durable, bounded Telegram delivery for comment conversations."""

from __future__ import annotations

import logging
from datetime import timedelta

from services import member_telegram
from utils import now_kst

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
RETRY_MINUTES = (1, 5, 15, 60, 180)


def _excerpt(value, limit=180):
    compact = " ".join(str(value or "").split())
    return compact if len(compact) <= limit else f"{compact[:limit].rstrip()}…"


def _message(*, post_title, comment_content, created_at, post_url):
    return (
        "💬 새 댓글 알림\n\n"
        f"게시글: {post_title}\n새 댓글: {_excerpt(comment_content)}\n"
        f"작성 시간: {created_at}\n\n게시글에서 확인 → {post_url}"
    )


def notify_new_comment(connection, *, scope_type, scope_id, author_id, comment_id,
                       post_title, comment_content, created_at, post_url, sender=None):
    """Subscribe the author and enqueue recipients without network I/O."""
    del sender, comment_id
    now_iso = now_kst().isoformat(timespec="seconds")
    text = _message(post_title=post_title, comment_content=comment_content,
                    created_at=created_at, post_url=post_url)
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
            """SELECT s.user_id FROM comment_telegram_subscriptions AS s
               JOIN member_telegram_connections AS c ON c.user_id=s.user_id
               JOIN dashboard_users AS u ON u.id=s.user_id
               WHERE s.scope_type=? AND s.scope_id=? AND s.is_active=1
                 AND c.enabled=1 AND c.notify_comments=1
                 AND u.is_active=1 AND u.approval_status='approved'
                 AND s.user_id<>?""",
            (str(scope_type), str(scope_id), int(author_id)),
        ).fetchall()
        for recipient in recipients:
            connection.execute(
                """INSERT INTO member_telegram_notification_queue
                   (recipient_user_id,notification_type,message,status,attempts,
                    available_at,created_at)
                   VALUES (?, 'comment', ?, 'pending', 0, ?, ?)""",
                (int(recipient["user_id"]), text, now_iso, now_iso),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        logger.exception("Failed to enqueue member comment Telegram notifications")
        return {"queued": 0, "failed": 0}
    return {"queued": len(recipients), "failed": 0}


def _finish(connection, queue_id, *, delivered, attempts, error_code=None):
    now = now_kst()
    if delivered:
        connection.execute(
            """UPDATE member_telegram_notification_queue
               SET status='sent',attempts=?,sent_at=?,last_error=NULL WHERE id=?""",
            (attempts, now.isoformat(timespec="seconds"), queue_id),
        )
    elif attempts >= MAX_ATTEMPTS:
        connection.execute(
            """UPDATE member_telegram_notification_queue
               SET status='failed',attempts=?,last_error=? WHERE id=?""",
            (attempts, error_code or "delivery_failed", queue_id),
        )
    else:
        delay = RETRY_MINUTES[min(attempts - 1, len(RETRY_MINUTES) - 1)]
        connection.execute(
            """UPDATE member_telegram_notification_queue
               SET status='pending',attempts=?,available_at=?,claimed_at=NULL,last_error=?
               WHERE id=?""",
            (attempts, (now + timedelta(minutes=delay)).isoformat(timespec="seconds"),
             error_code or "delivery_failed", queue_id),
        )
    connection.commit()


def process_pending(connection, *, limit=20, sender=None):
    """Claim and deliver a bounded queue batch with durable retries."""
    now = now_kst()
    now_iso = now.isoformat(timespec="seconds")
    connection.execute(
        """UPDATE member_telegram_notification_queue SET status='pending',claimed_at=NULL
           WHERE status='processing' AND claimed_at<?""",
        ((now - timedelta(minutes=15)).isoformat(timespec="seconds"),),
    )
    ids = [row["id"] for row in connection.execute(
        """SELECT id FROM member_telegram_notification_queue
           WHERE status='pending' AND available_at<=? ORDER BY id LIMIT ?""",
        (now_iso, max(1, min(int(limit), 100))),
    ).fetchall()]
    claimed = []
    for queue_id in ids:
        if connection.execute(
            """UPDATE member_telegram_notification_queue SET status='processing',claimed_at=?
               WHERE id=? AND status='pending'""", (now_iso, queue_id)
        ).rowcount:
            claimed.append(queue_id)
    connection.commit()

    send = sender or member_telegram.send_message
    sent_count = failed_count = 0
    for queue_id in claimed:
        row = connection.execute(
            """SELECT q.*,c.telegram_chat_id
               FROM member_telegram_notification_queue AS q
               LEFT JOIN member_telegram_connections AS c
                 ON c.user_id=q.recipient_user_id AND c.enabled=1 AND c.notify_comments=1
               JOIN dashboard_users AS u ON u.id=q.recipient_user_id
                 AND u.is_active=1 AND u.approval_status='approved'
               WHERE q.id=?""", (queue_id,)
        ).fetchone()
        attempts = int(row["attempts"] if row else 0) + 1
        if not row or not row["telegram_chat_id"]:
            _finish(connection, queue_id, delivered=False, attempts=MAX_ATTEMPTS,
                    error_code="recipient_unavailable")
            failed_count += 1
            continue
        try:
            delivered = bool(send(row["telegram_chat_id"], row["message"]))
        except Exception:
            delivered = False
            logger.exception("Queued member Telegram notification failed")
        _finish(connection, queue_id, delivered=delivered, attempts=attempts,
                error_code=None if delivered else "delivery_failed")
        sent_count += int(delivered)
        failed_count += int(not delivered)
    return {"claimed": len(claimed), "sent": sent_count, "failed": failed_count}

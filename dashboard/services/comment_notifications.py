"""Private, database-backed email notifications for comment conversations."""

import hashlib
import logging
import re
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage

import config
from utils import now_kst


logger = logging.getLogger("dashboard")
EMAIL_PATTERN = re.compile(r"[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{2,}")
SUBJECT = "새로운 댓글이 등록되었습니다."


def normalize_email(value):
    email = (value or "").strip().lower()
    if not email:
        return None
    if len(email) > 254 or not EMAIL_PATTERN.fullmatch(email):
        raise ValueError("올바른 이메일 주소를 입력해주세요.")
    return email


def _email_hash(email):
    return hashlib.sha256(email.encode("utf-8")).hexdigest()


def _excerpt(value, limit=180):
    text = " ".join((value or "").split())
    return text if len(text) <= limit else f"{text[:limit].rstrip()}…"


def _deliver(recipient, *, post_title, comment_excerpt, created_at, post_url):
    if not config.COMMENT_SMTP_HOST or not config.COMMENT_EMAIL_FROM:
        logger.warning("댓글 이메일 알림 SMTP 설정이 없어 발송하지 못했습니다.")
        return False

    message = EmailMessage()
    message["Subject"] = SUBJECT
    message["From"] = config.COMMENT_EMAIL_FROM
    message["To"] = recipient
    message.set_content(
        "\n".join((
            SUBJECT,
            "",
            f"게시글 제목: {post_title}",
            f"새 댓글: {comment_excerpt}",
            f"작성 시간: {created_at}",
            f"바로가기: {post_url}",
        ))
    )

    try:
        if config.COMMENT_SMTP_USE_SSL:
            smtp = smtplib.SMTP_SSL(
                config.COMMENT_SMTP_HOST,
                config.COMMENT_SMTP_PORT,
                timeout=config.COMMENT_SMTP_TIMEOUT_SECONDS,
                context=ssl.create_default_context(),
            )
        else:
            smtp = smtplib.SMTP(
                config.COMMENT_SMTP_HOST,
                config.COMMENT_SMTP_PORT,
                timeout=config.COMMENT_SMTP_TIMEOUT_SECONDS,
            )
        with smtp:
            if config.COMMENT_SMTP_STARTTLS and not config.COMMENT_SMTP_USE_SSL:
                smtp.starttls(context=ssl.create_default_context())
            if config.COMMENT_SMTP_USERNAME:
                smtp.login(config.COMMENT_SMTP_USERNAME, config.COMMENT_SMTP_PASSWORD)
            smtp.send_message(message)
        return True
    except (OSError, smtplib.SMTPException):
        # Never log the recipient address or SMTP credentials.
        logger.warning("댓글 이메일 알림 발송에 실패했습니다.")
        return False


def _record_delivery(
    connection, *, recipient_hash, scope_type, scope_id, comment_id, status,
    attempted_at, sent_at=None,
):
    connection.execute(
        """
        INSERT INTO comment_notification_deliveries (
            recipient_hash, scope_type, scope_id, comment_id, status,
            attempted_at, sent_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            recipient_hash, scope_type, str(scope_id), str(comment_id), status,
            attempted_at, sent_at,
        ),
    )


def _notify_new_comment(
    connection, *, scope_type, scope_id, author_id, notification_email,
    comment_id, post_title, comment_content, created_at, post_url,
):
    """Subscribe the author and notify prior participants without breaking comments."""
    email = normalize_email(notification_email)
    timestamp = now_kst().isoformat(timespec="seconds")
    if email:
        email_hash = _email_hash(email)
        connection.execute(
            """
            UPDATE comment_notification_subscriptions
            SET is_active=0, updated_at=?
            WHERE scope_type=? AND scope_id=? AND author_id=? AND email_hash<>?
            """,
            (timestamp, scope_type, str(scope_id), author_id, email_hash),
        )
        connection.execute(
            """
            INSERT INTO comment_notification_subscriptions (
                scope_type, scope_id, author_id, email, email_hash,
                is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(scope_type, scope_id, email_hash) DO UPDATE SET
                author_id=excluded.author_id, email=excluded.email,
                is_active=1, updated_at=excluded.updated_at
            """,
            (
                scope_type, str(scope_id), author_id, email, email_hash,
                timestamp, timestamp,
            ),
        )
    else:
        email_hash = None
    connection.commit()

    recipients = connection.execute(
        """
        SELECT email, email_hash FROM comment_notification_subscriptions
        WHERE scope_type=? AND scope_id=? AND is_active=1
          AND author_id<>? AND (? IS NULL OR email_hash<>?)
        ORDER BY id
        """,
        (scope_type, str(scope_id), author_id, email_hash, email_hash),
    ).fetchall()

    cutoff = (now_kst() - timedelta(hours=24)).isoformat(timespec="seconds")
    claim_cutoff = (now_kst() - timedelta(minutes=10)).isoformat(timespec="seconds")
    for recipient in recipients:
        attempted_at = now_kst().isoformat(timespec="seconds")
        recipient_hash = recipient["email_hash"]
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT OR IGNORE INTO comment_notification_rate_limits (
                    email_hash, last_success_at, sending_started_at, updated_at
                ) VALUES (?, NULL, NULL, ?)
                """,
                (recipient_hash, attempted_at),
            )
            claimed = connection.execute(
                """
                UPDATE comment_notification_rate_limits
                SET sending_started_at=?, updated_at=?
                WHERE email_hash=?
                  AND (last_success_at IS NULL OR last_success_at<=?)
                  AND (sending_started_at IS NULL OR sending_started_at<=?)
                """,
                (
                    attempted_at, attempted_at, recipient_hash, cutoff,
                    claim_cutoff,
                ),
            ).rowcount
            if not claimed:
                _record_delivery(
                    connection, recipient_hash=recipient_hash,
                    scope_type=scope_type, scope_id=scope_id,
                    comment_id=comment_id, status="rate_limited",
                    attempted_at=attempted_at,
                )
                connection.commit()
                continue
            connection.commit()

            sent = _deliver(
                recipient["email"], post_title=post_title,
                comment_excerpt=_excerpt(comment_content),
                created_at=created_at, post_url=post_url,
            )
            completed_at = now_kst().isoformat(timespec="seconds")
            if sent:
                connection.execute(
                    """
                    UPDATE comment_notification_rate_limits
                    SET last_success_at=?, sending_started_at=NULL, updated_at=?
                    WHERE email_hash=?
                    """,
                    (completed_at, completed_at, recipient_hash),
                )
            else:
                connection.execute(
                    """
                    UPDATE comment_notification_rate_limits
                    SET sending_started_at=NULL, updated_at=? WHERE email_hash=?
                    """,
                    (completed_at, recipient_hash),
                )
            _record_delivery(
                connection, recipient_hash=recipient_hash,
                scope_type=scope_type, scope_id=scope_id,
                comment_id=comment_id, status="sent" if sent else "failed",
                attempted_at=attempted_at, sent_at=completed_at if sent else None,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            logger.warning("댓글 이메일 알림 처리에 실패했습니다.")


def notify_new_comment(connection, **values):
    """Best-effort wrapper: notification faults never break comment creation."""
    try:
        return _notify_new_comment(connection, **values)
    except Exception:
        connection.rollback()
        logger.warning("댓글 이메일 알림 준비에 실패했습니다.")
        return None

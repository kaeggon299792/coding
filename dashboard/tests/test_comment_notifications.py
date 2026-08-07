from datetime import timedelta
from pathlib import Path

import pytest

from dashboard_db import schema
from services import comment_notifications
from utils import now_kst


ROOT = Path(__file__).resolve().parent.parent


def _notify(connection, *, author_id, email, comment_id, scope_id="post-1"):
    comment_notifications.notify_new_comment(
        connection,
        scope_type="community_post",
        scope_id=scope_id,
        author_id=author_id,
        notification_email=email,
        comment_id=comment_id,
        post_title="테스트 게시글",
        comment_content="새 댓글의 전체 내용은 이메일에 과도하게 포함되지 않아야 합니다.",
        created_at="2026-08-07T10:00:00+09:00",
        post_url="https://www.casinoin.kr/board/1#comments",
    )


def test_comment_email_validation_and_private_form_markup():
    assert comment_notifications.normalize_email(" User@Example.COM ") == "user@example.com"
    assert comment_notifications.normalize_email("") is None
    for value in ("broken", "a@", "@example.com", "a b@example.com"):
        with pytest.raises(ValueError, match="올바른 이메일"):
            comment_notifications.normalize_email(value)

    partial = (ROOT / "templates" / "_comment_notification_email.html").read_text("utf-8")
    assert 'type="email"' in partial
    assert 'name="notification_email"' in partial
    assert "이메일 주소는 댓글 알림 발송 목적으로만 사용되며 공개되지 않습니다." in partial
    for template in (
        "action_item_detail.html", "community_post.html", "tips/detail.html",
        "_company_content_comments.html",
    ):
        assert '_comment_notification_email.html' in (ROOT / "templates" / template).read_text("utf-8")


def test_smtp_message_contains_required_fields_and_truncated_excerpt(monkeypatch):
    messages = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self, **kwargs):
            return None

        def login(self, username, password):
            return None

        def send_message(self, message):
            messages.append(message)

    monkeypatch.setattr("config.COMMENT_SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr("config.COMMENT_SMTP_PORT", 587)
    monkeypatch.setattr("config.COMMENT_EMAIL_FROM", "notice@example.com")
    monkeypatch.setattr("config.COMMENT_SMTP_USERNAME", "")
    monkeypatch.setattr("config.COMMENT_SMTP_PASSWORD", "")
    monkeypatch.setattr("config.COMMENT_SMTP_USE_SSL", False)
    monkeypatch.setattr("config.COMMENT_SMTP_STARTTLS", True)
    monkeypatch.setattr(comment_notifications.smtplib, "SMTP", FakeSMTP)

    long_comment = "긴 댓글 " * 100
    assert comment_notifications._deliver(
        "reader@example.com",
        post_title="게시글 제목",
        comment_excerpt=comment_notifications._excerpt(long_comment),
        created_at="2026-08-07 10:00",
        post_url="https://www.casinoin.kr/board/1#comments",
    ) is True
    message = messages[0]
    body = message.get_content()
    assert message["Subject"] == "새로운 댓글이 등록되었습니다."
    assert "게시글 제목: 게시글 제목" in body
    assert "작성 시간: 2026-08-07 10:00" in body
    assert "https://www.casinoin.kr/board/1#comments" in body
    assert len(comment_notifications._excerpt(long_comment)) <= 181


def test_success_rate_limit_expiry_and_restart_persistence(tmp_path, monkeypatch):
    db_path = tmp_path / "notifications.db"
    connection = schema.connect(str(db_path))
    sent_to = []
    monkeypatch.setattr(
        comment_notifications, "_deliver",
        lambda recipient, **kwargs: sent_to.append(recipient) or True,
    )

    _notify(connection, author_id=1, email="first@example.com", comment_id=1)
    assert sent_to == []
    _notify(connection, author_id=2, email="second@example.com", comment_id=2)
    assert sent_to == ["first@example.com"]
    success = connection.execute(
        "SELECT status, sent_at FROM comment_notification_deliveries ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert success["status"] == "sent"
    assert success["sent_at"]
    connection.close()

    # A new DB connection simulates a restarted web process. The persisted
    # successful timestamp must still block another email inside 24 hours.
    connection = schema.connect(str(db_path))
    _notify(connection, author_id=3, email="third@example.com", comment_id=3)
    assert sent_to == ["first@example.com", "second@example.com"]
    assert connection.execute(
        "SELECT status FROM comment_notification_deliveries "
        "WHERE recipient_hash=? ORDER BY id DESC LIMIT 1",
        (comment_notifications._email_hash("first@example.com"),),
    ).fetchone()["status"] == "rate_limited"

    expired = (now_kst() - timedelta(hours=25)).isoformat(timespec="seconds")
    connection.execute(
        "UPDATE comment_notification_rate_limits SET last_success_at=? WHERE email_hash=?",
        (expired, comment_notifications._email_hash("first@example.com")),
    )
    connection.commit()
    _notify(connection, author_id=4, email="fourth@example.com", comment_id=4)
    assert sent_to.count("first@example.com") == 2
    connection.close()


def test_self_notification_is_excluded_even_with_another_email(tmp_path, monkeypatch):
    connection = schema.connect(str(tmp_path / "self.db"))
    delivered = []
    monkeypatch.setattr(
        comment_notifications, "_deliver",
        lambda recipient, **kwargs: delivered.append(recipient) or True,
    )
    _notify(connection, author_id=7, email="original@example.com", comment_id=1)
    _notify(connection, author_id=7, email="changed@example.com", comment_id=2)
    assert delivered == []
    assert connection.execute(
        "SELECT COUNT(*) FROM comment_notification_subscriptions "
        "WHERE scope_type='community_post' AND scope_id='post-1' AND is_active=1"
    ).fetchone()[0] == 1
    connection.close()


def test_failed_delivery_does_not_start_24_hour_limit_or_log_email(
    tmp_path, monkeypatch, caplog,
):
    connection = schema.connect(str(tmp_path / "failure.db"))
    monkeypatch.setattr(comment_notifications, "_deliver", lambda *args, **kwargs: False)
    _notify(connection, author_id=1, email="private@example.com", comment_id=1)
    _notify(connection, author_id=2, email="second@example.com", comment_id=2)
    rate = connection.execute(
        "SELECT last_success_at, sending_started_at FROM comment_notification_rate_limits "
        "WHERE email_hash=?",
        (comment_notifications._email_hash("private@example.com"),),
    ).fetchone()
    assert rate["last_success_at"] is None
    assert rate["sending_started_at"] is None
    assert connection.execute(
        "SELECT status FROM comment_notification_deliveries ORDER BY id DESC LIMIT 1"
    ).fetchone()["status"] == "failed"
    assert "private@example.com" not in caplog.text
    connection.close()


def test_comment_queries_never_return_private_subscription_email(tmp_path):
    connection = schema.connect(str(tmp_path / "privacy.db"))
    _notify(connection, author_id=1, email="hidden@example.com", comment_id=1)
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(community_comments)")
    }
    assert "email" not in columns
    assert "notification_email" not in columns
    connection.close()

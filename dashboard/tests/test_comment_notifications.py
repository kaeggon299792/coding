from pathlib import Path

from dashboard_db import schema
from services import comment_telegram_notifications
from utils import now_kst


ROOT = Path(__file__).resolve().parent.parent


def _user(connection, username):
    return connection.execute(
        """INSERT INTO dashboard_users
           (username,password_hash,role,is_active,approval_status,created_at)
           VALUES (?,'unused','user',1,'approved',?)""",
        (username, now_kst().isoformat()),
    ).lastrowid


def _connect(connection, user_id, chat_id, *, notify_comments=1):
    now = now_kst().isoformat(timespec="seconds")
    connection.execute(
        """INSERT INTO member_telegram_connections
           (user_id,telegram_chat_id,connected_at,updated_at,enabled,notify_comments)
           VALUES (?,?,?,?,1,?)""",
        (user_id, chat_id, now, now, notify_comments),
    )
    connection.commit()


def _notify(connection, *, author_id, comment_id, sender, scope_id="post-1"):
    return comment_telegram_notifications.notify_new_comment(
        connection,
        scope_type="community_post",
        scope_id=scope_id,
        author_id=author_id,
        comment_id=comment_id,
        post_title="테스트 게시글",
        comment_content="새 댓글의 전체 내용은 알림에 과도하게 포함되지 않아야 합니다.",
        created_at="2026-08-07T10:00:00+09:00",
        post_url="https://www.casinoin.kr/board/1#comments",
        sender=sender,
    )


def test_comment_form_disables_email_and_points_to_member_telegram():
    partial = (ROOT / "templates" / "_comment_notification_email.html").read_text("utf-8")
    assert 'type="email"' not in partial
    assert 'name="notification_email"' not in partial
    assert "새 댓글 알림은 Telegram" in partial
    for template in (
        "action_item_detail.html", "community_post.html", "tips/detail.html",
        "_company_content_comments.html",
    ):
        assert '_comment_notification_email.html' in (ROOT / "templates" / template).read_text("utf-8")


def test_comment_telegram_notifies_other_participants_without_rate_limit(tmp_path):
    connection = schema.connect(str(tmp_path / "comments.db"))
    first = _user(connection, "first")
    second = _user(connection, "second")
    _connect(connection, first, "111")
    _connect(connection, second, "222")
    sent = []
    sender = lambda chat_id, text: sent.append((chat_id, text)) or True

    assert _notify(connection, author_id=first, comment_id=1, sender=sender)["sent"] == 0
    assert _notify(connection, author_id=second, comment_id=2, sender=sender)["sent"] == 1
    assert sent[0][0] == "111"
    assert "테스트 게시글" in sent[0][1]
    assert _notify(connection, author_id=second, comment_id=3, sender=sender)["sent"] == 1
    assert [chat_id for chat_id, _ in sent] == ["111", "111"]
    connection.close()


def test_comment_telegram_excludes_self_and_disabled_preference(tmp_path):
    connection = schema.connect(str(tmp_path / "preferences.db"))
    first = _user(connection, "first")
    second = _user(connection, "second")
    _connect(connection, first, "111", notify_comments=0)
    _connect(connection, second, "222")
    sent = []
    sender = lambda chat_id, text: sent.append(chat_id) or True

    _notify(connection, author_id=first, comment_id=1, sender=sender)
    _notify(connection, author_id=second, comment_id=2, sender=sender)
    assert sent == []
    connection.close()

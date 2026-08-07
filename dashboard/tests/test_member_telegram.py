from datetime import timedelta
from pathlib import Path

from dashboard_db import schema
from services import member_telegram
from utils import now_kst


ROOT = Path(__file__).resolve().parent.parent


def _user(connection, username):
    return connection.execute(
        """INSERT INTO dashboard_users
           (username,password_hash,role,is_active,approval_status,created_at)
           VALUES (?,'unused','user',1,'approved',?)""",
        (username, now_kst().isoformat()),
    ).lastrowid


def test_member_telegram_token_is_one_time_expiring_and_user_isolated(tmp_path, monkeypatch):
    connection = schema.connect(str(tmp_path / "telegram.db"))
    first = _user(connection, "first")
    second = _user(connection, "second")
    monkeypatch.setattr("config.TELEGRAM_MEMBER_BOT_USERNAME", "casinoin_assistant_bot")
    current = now_kst()
    link = member_telegram.create_link(connection, first, current=current)
    raw = link.rsplit("=", 1)[1]

    assert member_telegram.consume_link(connection, raw, "1001", "first_tg", current=current)
    assert not member_telegram.consume_link(connection, raw, "1002", "second_tg", current=current)
    assert member_telegram.status(connection, first)["telegram_username"] == "first_tg"
    assert member_telegram.status(connection, second) is None

    expired = member_telegram.create_link(connection, second, current=current)
    expired_raw = expired.rsplit("=", 1)[1]
    assert not member_telegram.consume_link(
        connection, expired_raw, "1002", current=current + timedelta(minutes=16)
    )
    stored = connection.execute(
        "SELECT token_hash FROM member_telegram_link_tokens ORDER BY id LIMIT 1"
    ).fetchone()[0]
    assert raw not in stored
    connection.close()


def test_member_telegram_send_is_scoped_to_requested_user(tmp_path, monkeypatch):
    connection = schema.connect(str(tmp_path / "send.db"))
    first = _user(connection, "first")
    second = _user(connection, "second")
    now = now_kst().isoformat(timespec="seconds")
    connection.execute(
        """INSERT INTO member_telegram_connections
           (user_id,telegram_chat_id,connected_at,updated_at,enabled)
           VALUES (?,?,?,?,1)""", (first, "111", now, now)
    )
    connection.execute(
        """INSERT INTO member_telegram_connections
           (user_id,telegram_chat_id,connected_at,updated_at,enabled)
           VALUES (?,?,?,?,1)""", (second, "222", now, now)
    )
    sent = []
    monkeypatch.setattr(member_telegram, "send_message", lambda chat_id, text: sent.append(chat_id) or True)

    assert member_telegram.send_to_user(connection, first, "hello")
    assert sent == ["111"]
    connection.close()


def test_member_telegram_preferences_filter_broadcasts(tmp_path):
    connection = schema.connect(str(tmp_path / "preferences.db"))
    first = _user(connection, "first")
    second = _user(connection, "second")
    now = now_kst().isoformat(timespec="seconds")
    for user_id, chat_id in ((first, "111"), (second, "222")):
        connection.execute(
            """INSERT INTO member_telegram_connections
               (user_id,telegram_chat_id,connected_at,updated_at,enabled)
               VALUES (?,?,?,?,1)""", (user_id, chat_id, now, now)
        )
    connection.commit()

    assert member_telegram.update_preferences(
        connection, first,
        {"comments": False, "news": True, "recruitment": False},
    )
    state = member_telegram.status(connection, first)
    assert (state["notify_comments"], state["notify_news"], state["notify_recruitment"]) == (0, 1, 0)

    sent = []
    result = member_telegram.broadcast(
        connection, "news", "news", sender=lambda chat_id, text: sent.append(chat_id) or True
    )
    assert result == {"recipients": 2, "sent": 2, "failed": 0}
    result = member_telegram.broadcast(
        connection, "recruitment", "job", sender=lambda chat_id, text: sent.append(chat_id) or True
    )
    assert result["recipients"] == 1
    assert sent == ["111", "222", "222"]
    connection.close()


def test_member_telegram_page_opens_connect_and_exposes_three_preferences():
    template = (ROOT / "templates" / "member_telegram.html").read_text("utf-8")
    assert 'action="{{ url_for(\'member_area.telegram_connect\') }}" target="_blank"' in template
    for field in ("notify_comments", "notify_news", "notify_recruitment"):
        assert f'name="{field}"' in template

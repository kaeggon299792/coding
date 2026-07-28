from dashboard_db import queries
from flask import session


def test_manual_action_item_is_created_approved_by_default(db_connection):
    item_id = queries.create_action_item(db_connection, title="계약서 검토")
    item = queries.get_action_item(db_connection, item_id)
    assert item["ai_suggested"] == 0
    assert item["approved_by_user"] == 1
    assert item["status"] == "not_started"


def test_ai_suggested_action_item_starts_unapproved(db_connection):
    item_id = queries.create_action_item(
        db_connection, title="AI가 제안한 후속 조치", ai_suggested=True,
        ai_recommended_action="담당 임원에게 회신 필요",
    )
    item = queries.get_action_item(db_connection, item_id)
    assert item["ai_suggested"] == 1
    assert item["approved_by_user"] == 0

    queries.approve_action_item(db_connection, item_id)
    item = queries.get_action_item(db_connection, item_id)
    assert item["approved_by_user"] == 1


def test_update_and_delete_action_item(db_connection):
    item_id = queries.create_action_item(db_connection, title="임시 과제")
    queries.update_action_item(db_connection, item_id, status="완료")
    item = queries.get_action_item(db_connection, item_id)
    assert item["status"] == "완료"
    assert item["completed_at"] is not None

    queries.delete_action_item(db_connection, item_id)
    assert queries.get_action_item(db_connection, item_id) is None


def test_count_action_items_excludes_completed(db_connection):
    queries.create_action_item(db_connection, title="진행 중 과제")
    done_id = queries.create_action_item(db_connection, title="완료된 과제")
    queries.update_action_item(db_connection, done_id, status="완료")

    assert queries.count_action_items(db_connection) == 1


def test_action_item_comments_support_create_edit_and_soft_delete(db_connection):
    user_id = db_connection.execute(
        """
        INSERT INTO dashboard_users
            (username, password_hash, role, is_active, created_at, updated_at)
        VALUES ('questioner', 'hash', 'user', 1, '2026-07-29', '2026-07-29')
        """
    ).lastrowid
    db_connection.commit()
    item_id = queries.create_action_item(
        db_connection, title="질문", reported_by="questioner"
    )

    comment_id = queries.create_action_item_comment(
        db_connection, item_id, user_id, "첫 답변"
    )
    comments = queries.list_action_item_comments(db_connection, item_id)
    assert comments[0]["content"] == "첫 답변"
    assert comments[0]["author_name"] == "questioner"

    queries.update_action_item_comment(db_connection, comment_id, "수정 답변")
    assert queries.get_action_item_comment(db_connection, comment_id)["content"] == "수정 답변"

    queries.delete_action_item_comment(db_connection, comment_id, user_id)
    assert queries.list_action_item_comments(db_connection, item_id) == []


def test_bug_post_access_is_limited_to_author_and_admin():
    from app import app, can_access_action_item

    item = {"reported_by": "writer"}
    with app.test_request_context("/bug-reports/1"):
        session.update(user_id=1, username="writer", role="user")
        assert can_access_action_item(item)

        session.update(user_id=2, username="other", role="user")
        assert not can_access_action_item(item)

        session.update(user_id=3, username="admin", role="admin")
        assert can_access_action_item(item)

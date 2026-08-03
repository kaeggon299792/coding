import pytest

from dashboard_db import queries


def _user(connection, username):
    user_id = connection.execute(
        """
        INSERT INTO dashboard_users
            (username, password_hash, role, is_active, created_at, updated_at)
        VALUES (?, 'hash', 'user', 1, '2026-08-03', '2026-08-03')
        """,
        (username,),
    ).lastrowid
    connection.commit()
    return user_id


def test_community_comments_create_list_and_soft_delete(db_connection):
    user_id = _user(db_connection, "commenter")
    post_id = queries.create_community_post(
        db_connection, user_id, "commenter", "제목", "본문"
    )
    comment_id = queries.create_community_comment(
        db_connection, post_id, user_id, "commenter", "첫 댓글"
    )
    comments = queries.list_community_comments(db_connection, post_id)
    assert comments[0]["id"] == comment_id
    assert comments[0]["content"] == "첫 댓글"
    queries.soft_delete_community_comment(db_connection, comment_id, user_id)
    assert queries.list_community_comments(db_connection, post_id) == []


def test_community_comment_validation(db_connection):
    user_id = _user(db_connection, "validator")
    post_id = queries.create_community_post(
        db_connection, user_id, "validator", "제목", "본문"
    )
    with pytest.raises(ValueError):
        queries.create_community_comment(
            db_connection, post_id, user_id, "validator", ""
        )
    with pytest.raises(ValueError):
        queries.create_community_comment(
            db_connection, post_id, user_id, "validator", "x" * 1001
        )
    with pytest.raises(ValueError):
        queries.create_community_comment(
            db_connection, 999999, user_id, "validator", "댓글"
        )

import pytest

from dashboard_db import queries


def _user(connection, username):
    return connection.execute(
        """INSERT INTO dashboard_users
           (username,password_hash,role,is_active,approval_status,created_at)
           VALUES (?,'unused','user',1,'approved',datetime('now'))""",
        (username,),
    ).lastrowid


def test_generic_recommendation_is_unique_per_user_and_target(db_connection):
    user_id = _user(db_connection, "liker")
    active, count = queries.toggle_content_recommendation(
        db_connection, "tips", 17, user_id
    )
    assert active is True and count == 1
    state = queries.content_recommendation_state(db_connection, "tips", 17, user_id)
    assert state == {"recommendation_count": 1, "recommended_by_current_user": True}
    active, count = queries.toggle_content_recommendation(
        db_connection, "tips", 17, user_id
    )
    assert active is False and count == 0


def test_generic_recommendation_rejects_unapproved_scope(db_connection):
    with pytest.raises(ValueError):
        queries.content_recommendation_state(db_connection, "admin_log", 1, None)

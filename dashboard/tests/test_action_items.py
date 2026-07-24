from dashboard_db import queries


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

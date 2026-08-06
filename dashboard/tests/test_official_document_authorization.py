from services.official_document_manager import list_documents, list_documents_by_ids


def _insert_owned_document(connection, management_number, owner_id):
    cursor = connection.execute(
        """
        INSERT INTO official_documents
            (management_number, manager, receipt_date, organization,
             request_content, category_code, folder_category_code,
             registered_by, registered_user_id, registered_at, updated_at)
        VALUES (?, 'manager', '2026-08-06', 'organization', 'request',
                '03', '072', ?, ?, '2026-08-06T12:00:00+09:00',
                '2026-08-06T12:00:00+09:00')
        """,
        (management_number, f"user-{owner_id}", owner_id),
    )
    return cursor.lastrowid


def test_selected_document_lookup_can_be_scoped_to_owner(db_connection):
    db_connection.executemany(
        """
        INSERT INTO dashboard_users
            (id, username, password_hash, role, is_active, approval_status, created_at)
        VALUES (?, ?, 'unused', 'user', 1, 'approved', '2026-08-06T12:00:00+09:00')
        """,
        ((101, "owner-a"), (202, "owner-b")),
    )
    first_id = _insert_owned_document(db_connection, "OWNER-A-1", 101)
    second_id = _insert_owned_document(db_connection, "OWNER-B-1", 202)

    assert [item["id"] for item in list_documents_by_ids(
        db_connection, [first_id, second_id], registered_user_id=101
    )] == [first_id]
    assert [item["id"] for item in list_documents_by_ids(
        db_connection, [first_id, second_id]
    )] == [first_id, second_id]


def test_document_list_paginates_in_sql_and_preserves_owner_filter(db_connection):
    db_connection.executemany(
        """
        INSERT INTO dashboard_users
            (id, username, password_hash, role, is_active, approval_status, created_at)
        VALUES (?, ?, 'unused', 'user', 1, 'approved', '2026-08-06T12:00:00+09:00')
        """,
        ((301, "page-owner"), (302, "other-owner")),
    )
    owner_ids = [
        _insert_owned_document(db_connection, f"PAGE-A-{index}", 301)
        for index in range(5)
    ]
    _insert_owned_document(db_connection, "PAGE-B-1", 302)

    first_page, total = list_documents(
        db_connection,
        {"registered_user_id": 301, "sort": "management_number", "direction": "asc"},
        page=1,
        per_page=2,
    )
    second_page, second_total = list_documents(
        db_connection,
        {"registered_user_id": 301, "sort": "management_number", "direction": "asc"},
        page=2,
        per_page=2,
    )

    assert total == second_total == 5
    assert [item["id"] for item in first_page] == owner_ids[:2]
    assert [item["id"] for item in second_page] == owner_ids[2:4]


def test_document_visibility_hides_other_users_document():
    import app as app_module
    from flask import session
    from official_docs import _can_view_document

    with app_module.app.test_request_context("/official-docs/1"):
        session.update({"user_id": 101, "role": "user"})
        assert _can_view_document({"registered_user_id": 101}) is True
        assert _can_view_document({"registered_user_id": 202}) is False
        assert _can_view_document({"registered_user_id": None}) is False

        session.update({"user_id": 1, "role": "admin"})
        assert _can_view_document({"registered_user_id": 202}) is True

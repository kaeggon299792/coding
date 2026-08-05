from dashboard_db import queries


def test_missing_permission_rows_are_denied_by_default(db_connection):
    user_id = queries.create_user(db_connection, "permissionless", "unused-hash")

    permissions = queries.get_user_permissions(
        db_connection, user_id, ["companies", "official_docs"]
    )

    assert permissions == {"companies": False, "official_docs": False}

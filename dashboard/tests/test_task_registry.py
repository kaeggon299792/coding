from services import task_registry


def test_registry_groups_real_server_and_windows_tasks(db_connection):
    registry = task_registry.dashboard(db_connection)

    assert registry["counts"] == {
        "pythonanywhere_scheduled": 0,
        "pythonanywhere_always_on": 1,
        "windows_registered": 27,
    }
    assert {item["key"] for item in registry["pythonanywhere"]} >= {
        "law_sync", "dart_sync", "localization_translation", "telegram_ingest"
    }
    assert {item["key"] for item in registry["local"]} == {
        "local_board_watch", "local_datalab"
    }
    translation = next(
        item for item in registry["items"] if item["key"] == "localization_translation"
    )
    assert translation["schedule"] == "매일 23:30 KST"
    assert translation["platform_schedule"] == "14:30 UTC"
    assert translation["platform"] == "PythonAnywhere Always-on · CASINOINBOT"
    assert translation["managed_by"] == "CASINOINBOT"
    law = next(item for item in registry["items"] if item["key"] == "law_sync")
    assert law["mode"] == "묶음 실행"
    assert "유가·환율 갱신" in law["steps"]
    local = next(item for item in registry["items"] if item["key"] == "local_datalab")
    assert local["platform"] == "Windows 작업 스케줄러 (현재 로컬 PC)"
    assert local["mode"] == "동일 스크립트 다중 예약"


def test_admin_tasks_route_requires_admin(monkeypatch, tmp_path):
    import app as app_module
    from dashboard_db import schema

    db_path = tmp_path / "task-registry-routes.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    db = schema.connect(str(db_path))
    admin_id = db.execute(
        """INSERT INTO dashboard_users
               (username,password_hash,role,is_active,approval_status,created_at)
           VALUES ('task-admin','unused','admin',1,'approved','2026-08-04T00:00:00')"""
    ).lastrowid
    user_id = db.execute(
        """INSERT INTO dashboard_users
               (username,password_hash,role,is_active,approval_status,created_at)
           VALUES ('task-user','unused','user',1,'approved','2026-08-04T00:00:00')"""
    ).lastrowid
    db.commit()
    db.close()
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        assert client.get("/admin/tasks").status_code in {302, 401}
        with client.session_transaction() as session:
            session.update(user_id=user_id, username="task-user", role="user")
        assert client.get("/admin/tasks").status_code == 403
        with client.session_transaction() as session:
            session.clear()
            session.update(user_id=admin_id, username="task-admin", role="admin")
        response = client.get("/admin/tasks")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "자동화 작업 현황" in html
        assert "매일 23:30 KST" in html
        assert "Brity 게시판 알림" in html

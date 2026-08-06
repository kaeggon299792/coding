from io import BytesIO


def test_admin_memo_board_is_private_and_supports_safe_image(monkeypatch, tmp_path):
    import app as app_module
    from dashboard_db import schema

    db_path = tmp_path / "admin-memos.db"
    image_dir = tmp_path / "memo-images"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    monkeypatch.setattr("config.EDITOR_IMAGE_DIR", str(image_dir))
    db = schema.connect(str(db_path))
    admin_id = db.execute(
        """INSERT INTO dashboard_users
               (username,password_hash,role,is_active,approval_status,created_at)
           VALUES ('memo-admin','unused','admin',1,'approved','2026-08-06T00:00:00')"""
    ).lastrowid
    db.commit()
    db.close()
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        assert client.get("/admin/memos").status_code in {302, 401}
        with client.session_transaction() as session:
            session.update(
                user_id=admin_id, username="memo-admin", role="admin",
                csrf_token="valid",
            )
        created = client.post(
            "/admin/memos",
            data={
                "csrf_token": "valid",
                "purpose": "회의 준비",
                "content": "확인할 코드와 숫자",
                "image": (BytesIO(b"\x89PNG\r\n\x1a\nimage"), "unsafe.exe"),
            },
            content_type="multipart/form-data",
        )
        assert created.status_code == 302
        page = client.get("/admin/memos")
        assert page.status_code == 200
        assert "회의 준비" in page.get_data(as_text=True)
        assert "확인할 코드와 숫자" in page.get_data(as_text=True)
        admin_page = client.get("/admin")
        assert admin_page.status_code == 200
        assert 'href="/admin/memos"' in admin_page.get_data(as_text=True)

    db = schema.connect(str(db_path))
    memo = db.execute(
        "SELECT id,source_type,source_ref_id FROM action_items WHERE source_type='admin_memo'"
    ).fetchone()
    db.close()
    assert memo is not None
    assert memo["source_ref_id"].endswith(".png")
    stored = image_dir / memo["source_ref_id"].rsplit("/", 1)[-1]
    assert stored.exists()

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session.update(
                user_id=admin_id, username="memo-admin", role="admin",
                csrf_token="valid",
            )
        deleted = client.post(
            f"/admin/memos/{memo['id']}/delete", data={"csrf_token": "valid"}
        )
        assert deleted.status_code == 302
    assert not stored.exists()


def test_admin_memo_rejects_invalid_image(monkeypatch, tmp_path):
    import app as app_module
    from dashboard_db import schema

    db_path = tmp_path / "invalid-memo.db"
    image_dir = tmp_path / "memo-images"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    monkeypatch.setattr("config.EDITOR_IMAGE_DIR", str(image_dir))
    db = schema.connect(str(db_path))
    admin_id = db.execute(
        """INSERT INTO dashboard_users
               (username,password_hash,role,is_active,approval_status,created_at)
           VALUES ('memo-admin','unused','admin',1,'approved','2026-08-06T00:00:00')"""
    ).lastrowid
    db.commit()
    db.close()
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session.update(
                user_id=admin_id, username="memo-admin", role="admin",
                csrf_token="valid",
            )
        response = client.post(
            "/admin/memos",
            data={
                "csrf_token": "valid", "purpose": "테스트", "content": "내용",
                "image": (BytesIO(b"MZ executable"), "photo.png"),
            },
            content_type="multipart/form-data",
        )
        assert response.status_code == 302

    db = schema.connect(str(db_path))
    assert db.execute(
        "SELECT COUNT(*) FROM action_items WHERE source_type='admin_memo'"
    ).fetchone()[0] == 0
    db.close()

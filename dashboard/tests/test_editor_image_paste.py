from io import BytesIO
from pathlib import Path


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"safe-test-image"


def _create_user(connection, username, role):
    cursor = connection.execute(
        """INSERT INTO dashboard_users
           (username, password_hash, role, is_active, created_at)
           VALUES (?, 'unused', ?, 1, '2026-08-04T00:00:00')""",
        (username, role),
    )
    connection.commit()
    return cursor.lastrowid


def _login(client, user_id, username, role, csrf_token):
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = user_id
        browser_session["username"] = username
        browser_session["role"] = role
        browser_session["csrf_token"] = csrf_token


def _upload(client, scope, csrf_token, data=PNG_BYTES, filename="clipboard.svg"):
    return client.post(
        "/editor/images",
        data={
            "scope": scope,
            "csrf_token": csrf_token,
            "image": (BytesIO(data), filename),
        },
        content_type="multipart/form-data",
    )


def test_editor_image_upload_obeys_board_and_library_permissions(monkeypatch, tmp_path):
    db_path = tmp_path / "editor-images.db"
    image_dir = tmp_path / "editor-images"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    monkeypatch.setattr("config.EDITOR_IMAGE_DIR", str(image_dir))

    import app as app_module
    from dashboard_db import schema

    connection = schema.connect(str(db_path))
    regular_id = _create_user(connection, "paste-user", "user")
    admin_id = _create_user(connection, "paste-admin", "admin")
    connection.close()

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        assert _upload(client, "community", "x" * 64).status_code == 302

        _login(client, regular_id, "paste-user", "user", "u" * 64)
        community = _upload(client, "community", "u" * 64)
        assert community.status_code == 200
        assert community.get_json()["url"].startswith("/static/uploads/editor/")
        assert community.get_json()["url"].endswith(".png")
        assert _upload(client, "bug_report", "u" * 64).status_code == 200
        assert _upload(client, "notice", "u" * 64).status_code == 403
        assert _upload(client, "tips", "u" * 64).status_code == 403

        _login(client, admin_id, "paste-admin", "admin", "a" * 64)
        assert _upload(client, "notice", "a" * 64).status_code == 200
        assert _upload(client, "tips", "a" * 64).status_code == 200
        assert _upload(client, "tips", "wrong").status_code == 400
        invalid = _upload(client, "tips", "a" * 64, b"<svg><script>x</script></svg>")
        assert invalid.status_code == 400
        assert "PNG, JPG, GIF, WebP" in invalid.get_json()["error"]

    saved = list(image_dir.iterdir())
    assert len(saved) == 4
    assert all(path.suffix == ".png" and path.read_bytes() == PNG_BYTES for path in saved)


def test_markdown_editors_enable_clipboard_images_and_render_safely():
    import app as app_module

    root = Path(__file__).parents[1]
    board = (root / "templates" / "community_board.html").read_text(encoding="utf-8")
    tips = (root / "templates" / "tips" / "form.html").read_text(encoding="utf-8")
    bug_board = (root / "templates" / "action_items.html").read_text(encoding="utf-8")
    script = (root / "static" / "js" / "markdown-image-paste.js").read_text(
        encoding="utf-8"
    )
    assert 'data-image-paste-scope="{{ \'notice\' if is_notice_board else \'community\' }}"' in board
    assert 'data-image-paste-scope="tips"' in tips
    assert 'data-image-paste-scope="bug_report"' in bug_board
    assert 'data-image-upload-for="bug-report-description"' in bug_board
    assert 'event.clipboardData?.items' in script
    assert 'formData.append("csrf_token"' in script
    assert "data-image-upload-for" in script

    rendered = str(app_module._render_community_markdown(
        "![안전 이미지](/static/uploads/editor/test.png)\n\n"
        "![위험 이미지](javascript:alert(1))"
    ))
    assert '<img alt="안전 이미지" src="/static/uploads/editor/test.png">' in rendered
    assert "javascript:" not in rendered

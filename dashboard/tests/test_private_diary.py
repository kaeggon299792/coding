from io import BytesIO

from dashboard_db import schema


PNG_BYTES = b"\x89PNG\r\n\x1a\nprivate-diary-image"


def _user(connection, username):
    user_id = connection.execute(
        """INSERT INTO dashboard_users
           (username,password_hash,role,is_active,created_at,updated_at,membership_level)
           VALUES (?, 'hash', 'user', 1, '2026-08-06', '2026-08-06', 'gold')""",
        (username,),
    ).lastrowid
    connection.commit()
    return user_id


def _login(client, user_id, username, csrf):
    with client.session_transaction() as browser_session:
        browser_session.update(
            user_id=user_id, username=username, role="user", csrf_token=csrf
        )


def test_diary_entries_and_images_are_owner_only(monkeypatch, tmp_path):
    db_path = tmp_path / "diary.db"
    image_dir = tmp_path / "diary-images"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    monkeypatch.setattr("config.DIARY_IMAGE_DIR", str(image_dir))
    import app as app_module

    connection = schema.connect(str(db_path))
    owner_id = _user(connection, "diary-owner")
    other_id = _user(connection, "diary-other")
    connection.close()

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        assert client.get("/board/diary").status_code == 302
        _login(client, owner_id, "diary-owner", "o" * 64)
        created = client.post(
            "/board/diary",
            data={
                "csrf_token": "o" * 64,
                "diary_date": "2026-08-06",
                "mood_code": "good",
                "title": "오늘의 기록",
                "content": "나만 보는 내용",
            },
        )
        assert created.status_code == 302
        entry_url = created.headers["Location"]
        entry_id = int(entry_url.rstrip("/").split("/")[-1])
        assert "나만 보는 내용" in client.get(entry_url).get_data(as_text=True)
        assert client.get(f"/board/{entry_id}").status_code == 404

        uploaded = client.post(
            "/board/diary/images",
            data={
                "csrf_token": "o" * 64,
                "image": (BytesIO(PNG_BYTES), "pasted.svg"),
            },
            content_type="multipart/form-data",
        )
        assert uploaded.status_code == 200
        image_url = uploaded.get_json()["url"]
        assert client.get(image_url).data == PNG_BYTES

        _login(client, other_id, "diary-other", "x" * 64)
        assert client.get(entry_url).status_code == 404
        assert client.get(image_url).status_code == 404
        assert client.post(
            f"/board/diary/{entry_id}/delete",
            data={"csrf_token": "x" * 64},
        ).status_code == 404


def test_diary_validates_csrf_date_and_mood(monkeypatch, tmp_path):
    db_path = tmp_path / "diary-validation.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    import app as app_module

    connection = schema.connect(str(db_path))
    user_id = _user(connection, "diary-validator")
    connection.close()
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        _login(client, user_id, "diary-validator", "v" * 64)
        invalid_csrf = client.post(
            "/board/diary",
            data={"csrf_token": "bad", "diary_date": "2026-08-06",
                  "mood_code": "good", "title": "제목", "content": "본문"},
        )
        assert invalid_csrf.status_code == 400
        invalid_form = client.post(
            "/board/diary",
            data={"csrf_token": "v" * 64, "diary_date": "not-a-date",
                  "mood_code": "unknown", "title": "제목", "content": "본문"},
        )
        assert invalid_form.status_code == 400


def test_diary_mood_is_a_large_dropdown(monkeypatch, tmp_path):
    db_path = tmp_path / "diary-moods.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    import app as app_module

    connection = schema.connect(str(db_path))
    user_id = _user(connection, "diary-moods")
    connection.close()
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        _login(client, user_id, "diary-moods", "m" * 64)
        page = client.get("/board/diary").get_data(as_text=True)
        assert '<select class="diary-mood-select" name="mood_code"' in page
        assert page.count('<option value="') >= 30
        assert "🤩 황홀함" in page
        assert "🪫 지침" in page

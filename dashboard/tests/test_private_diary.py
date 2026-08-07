from io import BytesIO
import sqlite3

from dashboard_db import queries, schema
from services import membership


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
                "is_private": "1",
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
        assert "오늘의 기록" not in client.get("/board/diary").get_data(as_text=True)
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
        assert page.count('<option value="') == 151
        assert "🤩 황홀함" in page
        assert "🪫 지침" in page
        assert "🕯️ 깊이 슬픔" in page
        assert 'data-diary-date-button' in page
        assert 'js/diary.js' in page


def test_diary_timeline_and_gallery_paginate_ten_entries(monkeypatch, tmp_path):
    db_path = tmp_path / "diary-views.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    import app as app_module

    connection = schema.connect(str(db_path))
    user_id = _user(connection, "diary-views")
    image_url = "/board/diary/images/" + ("a" * 32) + ".png"
    for index in range(11):
        queries.create_diary_entry(
            connection,
            user_id,
            "diary-views",
            f"2026-07-{index + 1:02d}",
            "calm",
            f"기록 {index + 1}",
            (
                f"## 마크다운 본문 {index + 1}\n\n내용입니다."
                + (f"\n\n![테스트]({image_url})" if index == 10 else "")
            ),
        )
    connection.close()

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        _login(client, user_id, "diary-views", "t" * 64)
        timeline = client.get("/board/diary").get_data(as_text=True)
        assert timeline.count('class="diary-timeline-entry"') == 10
        assert "마크다운 본문 11" in timeline
        assert f'<img alt="테스트" src="{image_url}">' in timeline
        assert "page=2&amp;view=timeline" in timeline

        gallery = client.get("/board/diary?view=gallery").get_data(as_text=True)
        assert 'class="diary-gallery"' in gallery
        assert image_url in gallery
        assert "기록 11" in gallery
        assert "page=2&amp;view=gallery" in gallery

        invalid_view = client.get("/board/diary?view=unknown").get_data(as_text=True)
        assert 'class="diary-timeline"' in invalid_view


def test_public_diary_and_image_are_visible_to_other_members(monkeypatch, tmp_path):
    db_path = tmp_path / "public-diary.db"
    image_dir = tmp_path / "diary-images"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    monkeypatch.setattr("config.DIARY_IMAGE_DIR", str(image_dir))
    import app as app_module

    connection = schema.connect(str(db_path))
    owner_id = _user(connection, "public-diary-owner")
    viewer_id = _user(connection, "public-diary-viewer")
    connection.close()
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        _login(client, owner_id, "public-diary-owner", "p" * 64)
        uploaded = client.post(
            "/board/diary/images",
            data={
                "csrf_token": "p" * 64,
                "image": (BytesIO(PNG_BYTES), "public.png"),
            },
            content_type="multipart/form-data",
        )
        image_url = uploaded.get_json()["url"]
        created = client.post(
            "/board/diary",
            data={
                "csrf_token": "p" * 64,
                "diary_date": "2026-08-07",
                "mood_code": "happy",
                "title": "모두에게 보이는 기록",
                "content": f"공개 본문\n\n![공개 이미지]({image_url})",
            },
        )
        entry_url = created.headers["Location"]

    with app_module.app.test_client() as viewer:
        _login(viewer, viewer_id, "public-diary-viewer", "v" * 64)
        board = viewer.get("/board/diary")
        assert board.status_code == 200
        assert "모두에게 보이는 기록" in board.get_data(as_text=True)
        assert viewer.get(entry_url).status_code == 200
        assert viewer.get(image_url).status_code == 200

    with app_module.app.test_client() as owner:
        _login(owner, owner_id, "public-diary-owner", "p" * 64)
        private_update = owner.post(
            f"{entry_url}/edit",
            data={
                "csrf_token": "p" * 64,
                "diary_date": "2026-08-07",
                "mood_code": "happy",
                "title": "모두에게 보이는 기록",
                "content": f"공개 본문\n\n![공개 이미지]({image_url})",
                "is_private": "1",
            },
        )
        assert private_update.status_code == 302

    with app_module.app.test_client() as viewer:
        _login(viewer, viewer_id, "public-diary-viewer", "v" * 64)
        assert viewer.get(entry_url).status_code == 404
        assert viewer.get(image_url).status_code == 404


def test_review_board_defaults_to_gallery_and_is_separate(monkeypatch, tmp_path):
    db_path = tmp_path / "reviews.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    import app as app_module

    connection = schema.connect(str(db_path))
    user_id = _user(connection, "reviewer")
    review_image_url = "/board/diary/images/" + ("b" * 32) + ".png"
    queries.create_diary_entry(
        connection, user_id, "reviewer", "2026-08-07", "great",
        "첫 번째 리뷰", f"사진과 함께 작성한 리뷰\n\n![리뷰]({review_image_url})",
        board_type="review",
    )
    queries.create_diary_entry(
        connection, user_id, "reviewer", "2026-08-07", "calm",
        "아카이브 글", "서로 섞이면 안 됩니다.", board_type="diary",
    )
    connection.close()

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        assert client.get("/blog/reviews").status_code == 302
        _login(client, user_id, "reviewer", "r" * 64)
        review_page = client.get("/blog/reviews").get_data(as_text=True)
        assert "첫 번째 리뷰" in review_page
        assert "아카이브 글" not in review_page
        assert 'aria-current="page">갤러리</a>' in review_page
        assert "블로그" in review_page
        assert "아카이브" in review_page
        assert "리뷰 모음" in review_page
        assert "나의 기록" not in review_page


def test_archive_read_grade_is_member_by_default_and_admin_configurable(
    monkeypatch, tmp_path,
):
    db_path = tmp_path / "archive-permission.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    import app as app_module

    connection = schema.connect(str(db_path))
    gold_id = _user(connection, "archive-gold")
    platinum_id = _user(connection, "archive-platinum")
    connection.execute(
        "UPDATE dashboard_users SET membership_level='platinum' WHERE id=?",
        (platinum_id,),
    )
    permission = connection.execute(
        "SELECT read_grade FROM board_grade_permissions WHERE board_key='diary'"
    ).fetchone()
    assert permission["read_grade"] == "gold"
    membership.update_board_permission(
        connection, "diary", "platinum", "platinum", "platinum", actor_id=1,
    )
    connection.commit()
    connection.close()

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        assert client.get("/board/diary").status_code == 302
        _login(client, gold_id, "archive-gold", "g" * 64)
        assert client.get("/board/diary").status_code == 403

    with app_module.app.test_client() as client:
        _login(client, platinum_id, "archive-platinum", "p" * 64)
        assert client.get("/board/diary").status_code == 200


def test_schema_upgrade_preserves_existing_diaries_as_private(tmp_path):
    db_path = tmp_path / "legacy-diary.db"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE dashboard_users (
            id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE community_posts (
            id INTEGER PRIMARY KEY, author_id INTEGER NOT NULL,
            author_username TEXT NOT NULL, title TEXT NOT NULL,
            content TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, board_type TEXT NOT NULL DEFAULT 'community',
            is_deleted INTEGER NOT NULL DEFAULT 0, diary_date TEXT, mood_code TEXT
        );
        INSERT INTO dashboard_users VALUES (1, 'legacy', 'hash', '2026-08-01');
        INSERT INTO community_posts
            (id, author_id, author_username, title, content, created_at,
             updated_at, board_type, diary_date, mood_code)
        VALUES (1, 1, 'legacy', '기존 비공개 일기', '본문', '2026-08-01',
                '2026-08-01', 'diary', '2026-08-01', 'calm');
        """
    )
    connection.commit()
    schema.migrate(connection)
    assert connection.execute(
        "SELECT is_private FROM community_posts WHERE id=1"
    ).fetchone()[0] == 1
    connection.close()

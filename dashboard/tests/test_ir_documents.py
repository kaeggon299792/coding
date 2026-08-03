from io import BytesIO

from dashboard_db import queries, schema


def _create_document(connection, document_type, sha256):
    return queries.create_research_document(
        connection,
        document_type=document_type,
        company_name="GKL",
        company_names=["GKL"],
        title=f"{document_type} 문서",
        original_filename=f"{document_type}.pdf",
        stored_filename=f"{document_type}-{sha256[:8]}.pdf",
        mime_type="application/pdf",
        file_size=100,
        sha256=sha256,
        page_count=1,
        extracted_text="IR 핵심 내용",
        extraction_status="complete",
        uploaded_by="admin",
    )


def _configure_app_db(monkeypatch, tmp_path):
    db_path = tmp_path / "ir-route.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    import app as app_module

    connection = schema.connect(str(db_path))
    queries.upsert_monitored_company(connection, "GKL", "00557508")
    cursor = connection.execute(
        """
        INSERT INTO dashboard_users
            (username, password_hash, created_at, role, is_active)
        VALUES ('ir-admin', 'hash', '2026-08-01T00:00:00+09:00', 'admin', 1)
        """
    )
    connection.commit()
    user_id = cursor.lastrowid
    connection.close()
    app_module.app.config["TESTING"] = True
    return app_module, db_path, user_id


def _login(client, user_id, csrf="i" * 64):
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["username"] = "ir-admin"
        session["role"] = "admin"
        session["csrf_token"] = csrf


def test_document_type_migration_preserves_existing_research_rows(tmp_path):
    db_path = tmp_path / "document-type.db"
    connection = schema.connect(str(db_path))
    research_id = _create_document(connection, "research", "a" * 64)
    ir_id = _create_document(connection, "ir", "b" * 64)
    connection.close()

    connection = schema.connect(str(db_path))
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(research_documents)")
    }
    assert "document_type" in columns
    assert [item["id"] for item in queries.list_research_documents(connection)] == [
        research_id
    ]
    assert [
        item["id"]
        for item in queries.list_research_documents(connection, document_type="ir")
    ] == [ir_id]
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    connection.close()


def test_ir_upload_uses_gpt_title_and_stays_out_of_research_list(
    monkeypatch, tmp_path
):
    app_module, db_path, user_id = _configure_app_db(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "services.document_library.save_and_extract",
        lambda uploaded: {
            "original_filename": "gkl-ir.pdf",
            "stored_filename": "gkl-ir-stored.pdf",
            "mime_type": "application/pdf",
            "file_size": 100,
            "sha256": "c" * 64,
            "page_count": 5,
            "extracted_text": "GKL IR 성장 계획",
            "extraction_status": "complete",
            "path": tmp_path / "gkl-ir-stored.pdf",
        },
    )
    monkeypatch.setattr(
        "services.ai_insights.analyze_research_document",
        lambda connection, document: (
            {
                "suggested_title": "GPT 추천 IR 제목",
                "ai_summary": "IR 요약",
                "investment_stance": "중립",
                "industry_impact": "긍정",
                "key_points": ["성장 계획"],
                "risks": ["수요 변동"],
            },
            None,
        ),
    )
    with app_module.app.test_client() as client:
        _login(client, user_id)
        response = client.post(
            "/disclosures/ir",
            data={
                "csrf_token": "i" * 64,
                "company_name": "GKL",
                "title": "",
                "document": (BytesIO(b"fake"), "gkl-ir.pdf"),
            },
            content_type="multipart/form-data",
        )
    assert response.status_code == 302
    connection = schema.connect(str(db_path))
    assert queries.list_research_documents(connection) == []
    ir_document = queries.list_research_documents(
        connection, document_type="ir"
    )[0]
    assert ir_document["title"] == "GPT 추천 IR 제목"
    assert ir_document["ai_summary"] == "IR 요약"
    connection.close()


def test_ir_manual_title_wins_when_ai_suggests_another_title(monkeypatch, tmp_path):
    app_module, db_path, user_id = _configure_app_db(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "services.document_library.save_and_extract",
        lambda uploaded: {
            "original_filename": "manual.pdf", "stored_filename": "manual-stored.pdf",
            "mime_type": "application/pdf", "file_size": 10, "sha256": "e" * 64,
            "page_count": 1, "extracted_text": "IR", "extraction_status": "complete",
            "path": tmp_path / "manual-stored.pdf",
        },
    )
    monkeypatch.setattr(
        "services.ai_insights.analyze_research_document",
        lambda connection, document: ({"suggested_title": "GPT 제목", "ai_summary": "요약"}, None),
    )
    with app_module.app.test_client() as client:
        _login(client, user_id)
        response = client.post(
            "/disclosures/ir",
            data={"csrf_token": "i" * 64, "company_name": "GKL", "title": "수동 IR 제목", "document": (BytesIO(b"fake"), "manual.pdf")},
            content_type="multipart/form-data",
        )
    assert response.status_code == 302
    connection = schema.connect(str(db_path))
    assert queries.list_research_documents(connection, document_type="ir")[0]["title"] == "수동 IR 제목"
    connection.close()


def test_duplicate_ir_upload_is_rejected_and_temporary_file_removed(monkeypatch, tmp_path):
    app_module, db_path, user_id = _configure_app_db(monkeypatch, tmp_path)
    connection = schema.connect(str(db_path))
    _create_document(connection, "research", "f" * 64)
    connection.close()
    removed = []
    monkeypatch.setattr(
        "services.document_library.save_and_extract",
        lambda uploaded: {
            "original_filename": "duplicate.pdf", "stored_filename": "temporary.pdf",
            "mime_type": "application/pdf", "file_size": 10, "sha256": "f" * 64,
            "page_count": 1, "extracted_text": "IR", "extraction_status": "complete",
            "path": tmp_path / "temporary.pdf",
        },
    )
    monkeypatch.setattr("services.document_library.remove_file", removed.append)
    with app_module.app.test_client() as client:
        _login(client, user_id)
        response = client.post(
            "/disclosures/ir",
            data={"csrf_token": "i" * 64, "company_name": "GKL", "document": (BytesIO(b"fake"), "duplicate.pdf")},
            content_type="multipart/form-data",
        )
    assert response.status_code == 409
    assert removed == ["temporary.pdf"]
    connection = schema.connect(str(db_path))
    assert queries.list_research_documents(connection, document_type="ir") == []
    connection.close()


def test_ir_ai_failure_is_stored_safely_for_later_reanalysis(monkeypatch, tmp_path):
    app_module, db_path, user_id = _configure_app_db(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "services.document_library.save_and_extract",
        lambda uploaded: {
            "original_filename": "failed.pdf", "stored_filename": "failed-stored.pdf",
            "mime_type": "application/pdf", "file_size": 10, "sha256": "1" * 64,
            "page_count": 1, "extracted_text": "IR", "extraction_status": "complete",
            "path": tmp_path / "failed-stored.pdf",
        },
    )
    monkeypatch.setattr(
        "services.ai_insights.analyze_research_document",
        lambda connection, document: (None, "provider unavailable"),
    )
    with app_module.app.test_client() as client:
        _login(client, user_id)
        response = client.post(
            "/disclosures/ir",
            data={"csrf_token": "i" * 64, "company_name": "GKL", "document": (BytesIO(b"fake"), "failed.pdf")},
            content_type="multipart/form-data",
        )
    assert response.status_code == 302
    connection = schema.connect(str(db_path))
    document = queries.list_research_documents(connection, document_type="ir")[0]
    assert document["title"] == "failed"
    assert document["error_message"] == "provider unavailable"
    connection.close()


def test_ir_upload_rejects_missing_csrf(monkeypatch, tmp_path):
    app_module, _, user_id = _configure_app_db(monkeypatch, tmp_path)
    with app_module.app.test_client() as client:
        _login(client, user_id)
        response = client.post("/disclosures/ir", data={})
    assert response.status_code == 400


def test_user_without_disclosures_permission_cannot_upload(monkeypatch, tmp_path):
    app_module, db_path, user_id = _configure_app_db(monkeypatch, tmp_path)
    connection = schema.connect(str(db_path))
    connection.execute("UPDATE dashboard_users SET role='user' WHERE id=?", (user_id,))
    queries.replace_user_permissions(
        connection, user_id, ["disclosures"], [], updated_by="test"
    )
    connection.close()
    with app_module.app.test_client() as client:
        _login(client, user_id)
        response = client.post("/disclosures/ir", data={"csrf_token": "i" * 64})
    assert response.status_code == 403


def test_research_management_urls_cannot_manipulate_ir(monkeypatch, tmp_path):
    app_module, db_path, user_id = _configure_app_db(monkeypatch, tmp_path)
    connection = schema.connect(str(db_path))
    ir_id = _create_document(connection, "ir", "d" * 64)
    connection.close()
    with app_module.app.test_client() as client:
        _login(client, user_id)
        assert client.get(f"/library/{ir_id}/download").status_code == 404
        assert client.post(
            f"/library/{ir_id}/reanalyze", data={"csrf_token": "i" * 64}
        ).status_code == 404
        assert client.post(
            f"/library/{ir_id}/delete", data={"csrf_token": "i" * 64}
        ).status_code == 404
    connection = schema.connect(str(db_path))
    assert queries.get_research_document(connection, ir_id, document_type="ir")
    connection.close()


def test_ir_can_be_reanalyzed_and_deleted_by_disclosures_admin(monkeypatch, tmp_path):
    app_module, db_path, user_id = _configure_app_db(monkeypatch, tmp_path)
    connection = schema.connect(str(db_path))
    ir_id = _create_document(connection, "ir", "2" * 64)
    connection.close()
    analysis_calls = []
    monkeypatch.setattr(
        "services.ai_insights.analyze_research_document",
        lambda connection, document, *, bypass_daily_limits=False: (
            analysis_calls.append(bypass_daily_limits)
            or ({"ai_summary": "새 분석", "key_points": [], "risks": []}, None)
        ),
    )
    removed = []
    monkeypatch.setattr("services.document_library.remove_file", removed.append)
    with app_module.app.test_client() as client:
        _login(client, user_id)
        assert client.post(f"/disclosures/ir/{ir_id}/reanalyze", data={"csrf_token": "i" * 64}).status_code == 302
        assert client.post(f"/disclosures/ir/{ir_id}/delete", data={"csrf_token": "i" * 64}).status_code == 302
    assert removed == ["ir-22222222.pdf"]
    assert analysis_calls == [True]
    connection = schema.connect(str(db_path))
    assert queries.get_research_document(connection, ir_id, document_type="ir") is None
    connection.close()


def test_ir_reanalysis_replaces_only_filename_fallback_title(monkeypatch, tmp_path):
    app_module, db_path, user_id = _configure_app_db(monkeypatch, tmp_path)
    connection = schema.connect(str(db_path))
    fallback_id = _create_document(connection, "ir", "4" * 64)
    manual_id = _create_document(connection, "ir", "5" * 64)
    queries.update_research_document_title(
        connection, fallback_id, "ir", document_type="ir"
    )
    queries.update_research_document_title(
        connection, manual_id, "직접 입력한 제목", document_type="ir"
    )
    connection.close()
    monkeypatch.setattr(
        "services.ai_insights.analyze_research_document",
        lambda connection, document, *, bypass_daily_limits=False: (
            {
                "suggested_title": "파라다이스 2026년 1분기 실적 IR",
                "ai_summary": "새 분석",
                "key_points": [],
                "risks": [],
            },
            None,
        ),
    )
    with app_module.app.test_client() as client:
        _login(client, user_id)
        for document_id in (fallback_id, manual_id):
            response = client.post(
                f"/disclosures/ir/{document_id}/reanalyze",
                data={"csrf_token": "i" * 64},
            )
            assert response.status_code == 302
    connection = schema.connect(str(db_path))
    fallback = queries.get_research_document(connection, fallback_id, document_type="ir")
    manual = queries.get_research_document(connection, manual_id, document_type="ir")
    connection.close()
    assert fallback["title"] == "파라다이스 2026년 1분기 실적 IR"
    assert manual["title"] == "직접 입력한 제목"


def test_ir_title_can_be_edited_without_cross_type_access(monkeypatch, tmp_path):
    app_module, db_path, user_id = _configure_app_db(monkeypatch, tmp_path)
    connection = schema.connect(str(db_path))
    ir_id = _create_document(connection, "ir", "6" * 64)
    research_id = _create_document(connection, "research", "7" * 64)
    connection.close()
    with app_module.app.test_client() as client:
        _login(client, user_id)
        response = client.post(
            f"/disclosures/ir/{ir_id}/title",
            data={"csrf_token": "i" * 64, "title": "직접 수정한 IR 제목"},
        )
        assert response.status_code == 302
        assert client.post(
            f"/disclosures/ir/{research_id}/title",
            data={"csrf_token": "i" * 64, "title": "잘못된 수정"},
        ).status_code == 404
        assert client.post(
            f"/disclosures/ir/{ir_id}/title",
            data={"csrf_token": "invalid", "title": "CSRF 우회"},
        ).status_code == 302
    connection = schema.connect(str(db_path))
    ir_document = queries.get_research_document(connection, ir_id, document_type="ir")
    research_document = queries.get_research_document(
        connection, research_id, document_type="research"
    )
    connection.close()
    assert ir_document["title"] == "직접 수정한 IR 제목"
    assert research_document["title"] == "research 문서"


def test_public_disclosures_page_shows_ir_but_not_management_controls(monkeypatch, tmp_path):
    app_module, db_path, _ = _configure_app_db(monkeypatch, tmp_path)
    connection = schema.connect(str(db_path))
    _create_document(connection, "ir", "3" * 64)
    queries.save_disclosure(
        connection,
        "20260804000001",
        "GKL",
        "00557508",
        "분기보고서",
        "A",
        "20260804",
        "GKL",
        "https://dart.fss.or.kr/example",
        False,
    )
    connection.close()
    with app_module.app.test_client() as client:
        response = client.get("/disclosures")
    assert response.status_code == 200
    assert "ir 문서".encode() in response.data
    assert "분기보고서".encode() in response.data
    assert "기업 공시 자료".encode() in response.data
    assert b'id="ir-library-title"' not in response.data
    assert b"/disclosures/ir/1/reanalyze" not in response.data


def test_non_admin_cannot_see_or_call_ir_management(monkeypatch, tmp_path):
    app_module, db_path, user_id = _configure_app_db(monkeypatch, tmp_path)
    connection = schema.connect(str(db_path))
    connection.execute(
        "UPDATE dashboard_users SET role='user' WHERE id=?", (user_id,)
    )
    connection.commit()
    connection.close()
    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = user_id
            session["username"] = "ir-user"
            session["role"] = "user"
            session["csrf_token"] = "i" * 64
        page = client.get("/disclosures")
        assert page.status_code == 200
        assert "기업 IR 자료 등록" not in page.get_data(as_text=True)
        assert client.post(
            "/disclosures/ir", data={"csrf_token": "i" * 64}
        ).status_code == 403


def test_paradian_navigation_is_wrapped_in_admin_visibility_check():
    from pathlib import Path

    templates = Path(__file__).resolve().parent.parent / "templates"
    topbar = (templates / "_topbar.html").read_text(encoding="utf-8")
    home = (templates / "public_home.html").read_text(encoding="utf-8")
    assert "{% if current_user_role == 'admin' %}" in topbar
    assert "파라디안 전용" not in home


def test_admin_sees_paradian_and_ir_management(monkeypatch, tmp_path):
    app_module, _, user_id = _configure_app_db(monkeypatch, tmp_path)
    with app_module.app.test_client() as client:
        _login(client, user_id)
        disclosures = client.get("/disclosures").get_data(as_text=True)
        companies = client.get("/companies").get_data(as_text=True)
    assert "기업 IR 자료 등록" in disclosures
    assert "파라디안 전용" in companies


def test_non_admin_cannot_access_paradian_or_official_documents(monkeypatch, tmp_path):
    app_module, db_path, user_id = _configure_app_db(monkeypatch, tmp_path)
    connection = schema.connect(str(db_path))
    connection.execute("UPDATE dashboard_users SET role='user' WHERE id=?", (user_id,))
    connection.commit()
    connection.close()
    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = user_id
            session["username"] = "regular-user"
            session["role"] = "user"
            session["csrf_token"] = "i" * 64
        assert client.get("/paradian").status_code == 403
        assert client.get("/performance").status_code == 403
        assert client.get("/official-docs/").status_code == 403


def test_dart_source_button_has_accessible_non_wrapping_markup():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    template = (root / "templates" / "disclosures.html").read_text(encoding="utf-8")
    css = (root / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")
    assert "DART 원문 보기" in template
    assert 'rel="noopener noreferrer"' in template
    assert 'aria-label="{{ d.corp_name }} {{ d.report_nm }} DART 원문 보기"' in template
    assert ".disclosure-source-cell" in css and "white-space: nowrap" in css
    assert ".disclosure-source-button" in css and "inline-flex" in css
    assert "min-width: max-content" in css and "flex-shrink: 0" in css

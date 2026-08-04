from dashboard_db import queries, schema


def _create_document(connection):
    return queries.create_research_document(
        connection,
        company_name="파라다이스",
        company_names=["파라다이스"],
        title="기존 파일명",
        original_filename="report.pdf",
        stored_filename="report-test.pdf",
        mime_type="application/pdf",
        file_size=1024,
        sha256="a" * 64,
        page_count=3,
        extracted_text="카지노 산업 전망",
        extraction_status="completed",
        uploaded_by="tester",
    )


def test_research_analysis_stores_suggested_title_and_industry_impact(tmp_path):
    connection = schema.connect(str(tmp_path / "research-analysis.db"))
    document_id = _create_document(connection)
    queries.update_research_document_analysis(
        connection,
        document_id,
        analysis={
            "suggested_title": "파라다이스 카지노 산업 전망",
            "ai_summary": "요약",
            "investment_stance": "매수",
            "target_price": "25,000원",
            "industry_impact": "긍정",
            "key_points": ["외래객 회복"],
            "risks": ["환율 변동"],
        },
    )
    document = queries.get_research_document(connection, document_id)
    assert document["ai_suggested_title"] == "파라다이스 카지노 산업 전망"
    assert document["industry_impact"] == "긍정"
    connection.close()


def test_research_title_can_be_edited_or_replaced_with_ai_title(
    monkeypatch, tmp_path
):
    db_path = tmp_path / "research-title.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))

    import app as app_module

    connection = schema.connect(str(db_path))
    document_id = _create_document(connection)
    queries.update_research_document_analysis(
        connection,
        document_id,
        analysis={
            "suggested_title": "GPT 추천 제목",
            "ai_summary": "요약",
            "investment_stance": "중립",
            "target_price": "명시 없음",
            "industry_impact": "중립",
            "key_points": [],
            "risks": [],
        },
    )
    connection.close()

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = 987654
            session["username"] = "tester"
            session["role"] = "user"
            session["csrf_token"] = "r" * 64

        manual = client.post(
            f"/companies/reports/{document_id}/title",
            data={"csrf_token": "r" * 64, "title": "직접 수정한 제목"},
        )
        ai_title = client.post(
            f"/companies/reports/{document_id}/title",
            data={"csrf_token": "r" * 64, "title_mode": "ai"},
        )
        page = client.get("/companies/reports")

    assert manual.status_code == 302
    assert ai_title.status_code == 302
    assert page.status_code == 200
    assert "GPT 추천 제목".encode() in page.data
    assert "산업 영향도".encode() in page.data

    connection = schema.connect(str(db_path))
    assert (
        queries.get_research_document(connection, document_id)["title"]
        == "GPT 추천 제목"
    )
    connection.close()

from io import BytesIO

import pytest
from pypdf import PdfWriter
from werkzeug.datastructures import FileStorage

from dashboard_db import queries
from services import document_library


def _blank_pdf():
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(buffer)
    buffer.seek(0)
    return buffer


def test_pdf_is_saved_and_extracted_safely(monkeypatch, tmp_path):
    monkeypatch.setattr("config.RESEARCH_LIBRARY_DIR", str(tmp_path))
    uploaded = FileStorage(stream=_blank_pdf(), filename="../../broker-report.pdf")

    result = document_library.save_and_extract(uploaded)

    assert result["original_filename"] == "broker-report.pdf"
    assert result["stored_filename"].endswith(".pdf")
    assert result["page_count"] == 1
    assert result["extraction_status"] == "no_text"
    assert result["path"].parent == tmp_path


def test_korean_pdf_filename_is_preserved(monkeypatch, tmp_path):
    monkeypatch.setattr("config.RESEARCH_LIBRARY_DIR", str(tmp_path))
    uploaded = FileStorage(stream=_blank_pdf(), filename="파라다이스 증권사 리포트.PDF")

    result = document_library.save_and_extract(uploaded)

    assert result["original_filename"] == "파라다이스 증권사 리포트.pdf"


def test_research_document_round_trip(db_connection):
    document_id = queries.create_research_document(
        db_connection,
        company_name="GKL",
        title="카지노 산업 전망",
        publisher="테스트증권",
        report_date="2026-07-28",
        original_filename="report.pdf",
        stored_filename="abc.pdf",
        mime_type="application/pdf",
        file_size=1234,
        sha256="a" * 64,
        page_count=10,
        extracted_text="GKL 카지노 산업 전망",
        extraction_status="complete",
        uploaded_by="admin",
    )
    queries.update_research_document_analysis(
        db_connection,
        document_id,
        analysis={
            "ai_summary": "외래객 회복이 핵심이다.",
            "investment_stance": "매수",
            "target_price": "20,000원",
            "key_points": ["방문객 증가"],
            "risks": ["규제"],
        },
    )

    document = queries.get_research_document(db_connection, document_id)
    assert document["company_name"] == "GKL"
    assert document["key_points"] == ["방문객 증가"]
    assert document["risks"] == ["규제"]
    assert queries.search_research_documents(db_connection, "외래객")[0]["id"] == document_id


def test_library_upload_route_saves_and_analyzes(monkeypatch, tmp_path):
    db_path = tmp_path / "library_route.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))

    import app as app_module
    from extensions import dashboard_db

    connection = dashboard_db()
    queries.upsert_monitored_company(connection, "GKL", "00557508")
    connection.close()

    monkeypatch.setattr(
        "services.document_library.save_and_extract",
        lambda uploaded: {
            "original_filename": "gkl-report.pdf",
            "stored_filename": "stored.pdf",
            "mime_type": "application/pdf",
            "file_size": 100,
            "sha256": "c" * 64,
            "page_count": 5,
            "extracted_text": "GKL 외래객 회복",
            "extraction_status": "complete",
            "path": tmp_path / "stored.pdf",
        },
    )
    monkeypatch.setattr(
        "services.ai_insights.analyze_research_document",
        lambda connection, document: (
            {
                "suggested_title": "GPT 추천 제목",
                "ai_summary": "외래객 회복이 핵심이다.",
                "investment_stance": "매수",
                "target_price": "20,000원",
                "key_points": ["방문객 증가"],
                "risks": ["규제"],
            },
            None,
        ),
    )

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = 1
            session["username"] = "admin"
            session["csrf_token"] = "a" * 64
        response = client.post(
            "/library",
            data={
                "csrf_token": "a" * 64,
                "company_name": "GKL",
                "title": "GKL 전망",
                "document": (BytesIO(b"fake"), "gkl-report.pdf"),
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 302
    connection = dashboard_db()
    document = queries.list_research_documents(connection)[0]
    connection.close()
    assert document["title"] == "GKL 전망"
    assert document["ai_summary"] == "외래객 회복이 핵심이다."


@pytest.mark.parametrize(
    ("analysis", "analysis_error", "expected_title", "expected_ai_title"),
    (
        (
            {"suggested_title": "  GPT 생성 제목  ", "ai_summary": "요약"},
            None,
            "GPT 생성 제목",
            "GPT 생성 제목",
        ),
        (
            {"suggested_title": "   ", "ai_summary": "요약"},
            None,
            "gkl-report",
            None,
        ),
        (None, "AI 분석 실패", "gkl-report", None),
    ),
    ids=("gpt-title", "blank-gpt-title", "ai-failure"),
)
def test_library_upload_blank_title_uses_gpt_then_filename_fallback(
    monkeypatch,
    tmp_path,
    analysis,
    analysis_error,
    expected_title,
    expected_ai_title,
):
    db_path = tmp_path / "library_title_priority.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))

    import app as app_module
    from extensions import dashboard_db

    connection = dashboard_db()
    queries.upsert_monitored_company(connection, "GKL", "00557508")
    connection.close()

    monkeypatch.setattr(
        "services.document_library.save_and_extract",
        lambda uploaded: {
            "original_filename": "gkl-report.pdf",
            "stored_filename": "stored.pdf",
            "mime_type": "application/pdf",
            "file_size": 100,
            "sha256": "d" * 64,
            "page_count": 5,
            "extracted_text": "GKL 외래객 회복",
            "extraction_status": "complete",
            "path": tmp_path / "stored.pdf",
        },
    )
    monkeypatch.setattr(
        "services.ai_insights.analyze_research_document",
        lambda connection, document: (analysis, analysis_error),
    )

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = 1
            session["username"] = "admin"
            session["csrf_token"] = "b" * 64
        response = client.post(
            "/library",
            data={
                "csrf_token": "b" * 64,
                "company_name": "GKL",
                "title": "   ",
                "document": (BytesIO(b"fake"), "gkl-report.pdf"),
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 302
    connection = dashboard_db()
    document = queries.list_research_documents(connection)[0]
    connection.close()
    assert document["title"] == expected_title
    assert document["ai_suggested_title"] == expected_ai_title

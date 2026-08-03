import json

from dashboard_db import queries
from services import company_intelligence


def test_company_comparison_contains_four_default_companies(db_connection, monkeypatch):
    monkeypatch.setattr(
        "services.company_intelligence.news_reader.articles_for_aliases",
        lambda aliases, **kwargs: [],
    )

    companies = company_intelligence.build_company_comparison(db_connection, days=90)

    names = [company["name"] for company in companies]
    assert names[:4] == ["파라다이스", "GKL", "강원랜드", "롯데관광개발"]
    assert all("strategy_changes" in company for company in companies)


def test_registered_company_dart_code_enriches_default(db_connection, monkeypatch):
    queries.upsert_monitored_company(
        db_connection,
        "GKL",
        "12345678",
        aliases=["세븐럭카지노"],
    )
    monkeypatch.setattr(
        "services.company_intelligence.news_reader.articles_for_aliases",
        lambda aliases, **kwargs: [],
    )

    companies = company_intelligence.build_company_comparison(db_connection)
    gkl = next(company for company in companies if company["name"] == "GKL")

    assert gkl["dart_corp_code"] == "12345678"
    assert "세븐럭카지노" in gkl["aliases"]


def test_company_research_is_included_and_financials_are_formatted(db_connection, monkeypatch):
    queries.upsert_company_research(
        db_connection,
        "파라다이스",
        business_summary="복합리조트 운영",
        financials_json=json.dumps({"revenue": 1_149_867_026_461}),
        key_assets_json=json.dumps(["파라다이스시티"], ensure_ascii=False),
        opportunities_json="[]",
        risks_json="[]",
        sources_json="[]",
    )
    monkeypatch.setattr(
        "services.company_intelligence.news_reader.articles_for_aliases",
        lambda aliases, **kwargs: [],
    )

    companies = company_intelligence.build_company_comparison(db_connection)
    paradise = next(company for company in companies if company["name"] == "파라다이스")

    assert paradise["research"]["key_assets"] == ["파라다이스시티"]
    assert paradise["research"]["financial_metrics"][0]["display"] == "11,499억원"


def test_company_detail_combines_dart_filings_and_ir_documents(db_connection, monkeypatch):
    queries.save_disclosure(
        db_connection,
        "20260801000001",
        "파라다이스",
        "",
        "분기보고서",
        "A",
        "20260801",
        "파라다이스",
        "https://dart.fss.or.kr/example",
        False,
    )
    ir_document_id = queries.create_research_document(
        db_connection,
        document_type="ir",
        company_name="파라다이스",
        company_names=["파라다이스"],
        title="2026년 2분기 IR 자료",
        publisher="IR팀",
        report_date="2026-08-02",
        original_filename="paradise-ir.pdf",
        stored_filename="paradise-ir.pdf",
        mime_type="application/pdf",
        file_size=100,
        sha256="a" * 64,
        page_count=1,
        extracted_text="IR 본문",
        extraction_status="success",
        uploaded_by=1,
    )
    queries.create_research_document(
        db_connection,
        document_type="research",
        company_name="파라다이스",
        company_names=["파라다이스"],
        title="별도 리서치 자료",
        report_date="2026-08-03",
        original_filename="research.pdf",
        stored_filename="research.pdf",
        mime_type="application/pdf",
        file_size=100,
        sha256="b" * 64,
        page_count=1,
        extracted_text="리서치 본문",
        extraction_status="success",
        uploaded_by=1,
    )
    monkeypatch.setattr(
        "services.company_intelligence.news_reader.articles_for_aliases",
        lambda aliases, **kwargs: [],
    )

    context = company_intelligence.build_company_detail_context(
        db_connection, "파라다이스"
    )

    assert [item["source_type"] for item in context["company_filings"]] == [
        "ir",
        "dart",
    ]
    assert context["company_filings"][0]["document_id"] == ir_document_id
    assert [item["title"] for item in context["research_documents"]] == [
        "별도 리서치 자료"
    ]

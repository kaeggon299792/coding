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

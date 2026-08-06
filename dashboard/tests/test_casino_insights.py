from pathlib import Path

import pytest
from dashboard_db import schema
from scripts.import_epic_industry_data import import_epic_data
from services import casino_insights

DATA_FILE = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "epic_industry_metrics_20260806.json"
)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(tmp_path / "insights_route.db"))
    import app as app_module

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def _imported_database(tmp_path):
    database = tmp_path / "casino_insights.db"
    import_epic_data(database, DATA_FILE)
    return database


def test_insights_are_derived_from_central_repository(tmp_path):
    database = _imported_database(tmp_path)
    connection = schema.connect(str(database))
    try:
        result = casino_insights.build_dashboard(connection)
    finally:
        connection.close()

    assert result["has_data"] is True
    assert result["latest_period"] == "2026-07"
    assert {item["name"] for item in result["ranking"]} == {
        "파라다이스", "GKL", "드림타워"
    }
    assert [item["name"] for item in result["visitor_rows"]] == ["GKL", "드림타워"]
    assert all(0 <= item["score"] <= 100 for item in result["ranking"])
    assert all(item["spend_per_visitor"] > 0 for item in result["visitor_rows"])
    assert {item["name"] for item in result["nationality"]} == {"중국", "일본"}
    assert result["fund"]["year"] == "2025"
    assert len(result["recovery"]) == 3
    assert len(result["seasonality"]) == 12


def test_insights_handle_an_empty_repository(db_connection):
    result = casino_insights.build_dashboard(db_connection)
    assert result["has_data"] is False
    assert result["ranking"] == []
    assert len(result["seasonality"]) == 12


def test_casino_insights_page_is_public(client, monkeypatch):
    monkeypatch.setattr(
        "app.casino_insights.build_dashboard",
        lambda connection: {
            "has_data": False,
            "latest_period": None,
            "ranking": [],
        },
    )
    response = client.get("/market/casino-industry/insights")
    assert response.status_code == 200
    assert "카지노 인사이트".encode() in response.data
    assert "분석할 운영지표가 없습니다.".encode() in response.data


def test_casino_insights_page_renders_imported_metrics(tmp_path, monkeypatch):
    database = _imported_database(tmp_path)
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(database))
    import app as app_module

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        response = test_client.get("/market/casino-industry/insights")
    assert response.status_code == 200
    assert "카지노 흥행지수와 월간 파워랭킹".encode() in response.data
    assert "방문객 1인당 매출".encode() in response.data
    assert "한국 vs 마카오 회복 온도계".encode() in response.data
    assert "카지노 성수기 캘린더".encode() in response.data
    assert b"width:None%" not in response.data


def test_insights_page_is_in_public_sitemap(client):
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert b"https://www.casinoin.kr/market/casino-industry/insights" in response.data

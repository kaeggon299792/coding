import pytest

from services import casino_industry


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(tmp_path / "casino_test.db"))
    import app as app_module

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def test_casino_industry_totals_match_source_data():
    result = casino_industry.build_dashboard()
    assert result["summary"] == {
        "venue_count": 17,
        "area_sqm": 54531.61,
        "revenue_2024": 1861420,
        "visitors_2024": 2944457,
        "direct_count": 3,
        "leased_count": 14,
    }


def test_casino_industry_region_filter():
    result = casino_industry.build_dashboard("제주")
    assert len(result["items"]) == 8
    assert {item["region"] for item in result["items"]} == {"제주"}


def test_casino_industry_page_is_public(client):
    response = client.get("/performance/casino-industry")
    assert response.status_code == 200
    assert "카지노업 현황".encode() in response.data
    assert "파라다이스카지노 워커힐점".encode() in response.data

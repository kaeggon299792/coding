import pytest

from services import casino_industry, casino_statistics


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
        "area_sqm": 54857.15,
        "revenue_2025": 2263762,
        "visitors_2025": 3494051,
        "direct_count": 2,
        "leased_count": 15,
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
    assert "2,263,762".encode() in response.data


def test_casino_history_latest_values_match_report():
    visitors = casino_statistics.build_visitors()
    revenue = casino_statistics.build_revenue()
    fund = casino_statistics.build_fund()
    assert visitors["latest"]["casino_visitors"] == 3494051
    assert visitors["latest"]["share"] == 18.5
    assert revenue["latest"]["casino_income"] == 1590760
    assert revenue["latest"]["share"] == 7.3
    assert fund["latest"] == {
        "foreign_only": 219470,
        "kangwon": 142626,
        "total": 362096,
    }
    assert [tick["year"] for tick in visitors["year_ticks"]] == [
        1995, 2000, 2005, 2010, 2015, 2020, 2025
    ]
    assert visitors["casino_chart_points"][-1]["value"] == 3494051
    assert revenue["share_chart_points"][-1]["value"] == 7.3
    assert [tick["year"] for tick in fund["year_ticks"]] == [
        2016, 2018, 2020, 2022, 2024, 2025
    ]


@pytest.mark.parametrize(
    ("path", "title"),
    [
        ("/performance/casino-industry/visitors", "연도별 카지노 이용객"),
        ("/performance/casino-industry/revenue", "연도별 카지노 매출액 비율"),
        ("/performance/casino-industry/fund", "기금 부과 현황"),
    ],
)
def test_casino_statistics_pages_are_public(client, path, title):
    response = client.get(path)
    assert response.status_code == 200
    assert title.encode() in response.data
    assert b"casino-interactive-chart" in response.data
    assert b"casino-chart-hitpoint" in response.data
    assert b"casino-chart-tooltip" in response.data
    assert b"js/casino-charts.js" in response.data

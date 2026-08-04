import pytest

from services import casino_industry, casino_market_share, casino_statistics


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
    response = client.get("/market/casino-industry")
    assert response.status_code == 200
    assert b"casino-map-marker is-incheon" in response.data
    assert "국내 카지노 산업".encode() in response.data
    assert "파라다이스카지노 워커힐점".encode() in response.data
    assert "2,263,762".encode() in response.data


def test_casino_market_share_page_is_public(client):
    response = client.get("/market/casino-industry/market-share?year=2024")
    assert response.status_code == 200
    assert b"casino-ms-page" in response.data
    assert b'<option value="2024" selected>' in response.data
    assert b"20260805-market-share2" in response.data

    excluded = client.get(
        "/market/casino-industry/market-share?year=2024&exclude_kangwon=1"
    )
    assert excluded.status_code == 200
    assert b'name="exclude_kangwon" value="1" checked' in excluded.data


def test_market_share_uses_central_financial_values(monkeypatch):
    rows = [
        {"company_name": "강원랜드", "account_code": "121000", "fiscal_date": "2025-12-31", "amount": 100_000_000_000},
        {"company_name": "강원랜드", "account_code": "125000", "fiscal_date": "2025-12-31", "amount": 20_000_000_000},
        {"company_name": "GKL", "account_code": "121000", "fiscal_date": "2025-12-31", "amount": 50_000_000_000},
        {"company_name": "GKL", "account_code": "125000", "fiscal_date": "2025-12-31", "amount": 10_000_000_000},
    ]
    monkeypatch.setattr(
        "services.casino_market_share.queries.list_casino_market_share_financials",
        lambda connection, start_year, end_year: rows,
    )
    result = casino_market_share.build_dashboard(object(), 2025)
    assert result["selected_year"] == 2025
    assert result["comparisons"][0]["revenue_items"][0]["name"] == "외래객"
    assert result["comparisons"][0]["revenue_items"][0]["share"] == 33.3

    excluded = casino_market_share.build_dashboard(object(), 2025, True)
    assert excluded["exclude_kangwon"] is True
    assert all(item["name"] != "강원랜드" for item in excluded["trend"])


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
    assert visitors["casino_area_points"].startswith("24,236 ")
    assert visitors["casino_area_points"].endswith(" 896,236")
    assert revenue["share_chart_points"][-1]["value"] == 7.3
    assert revenue["share_area_points"].startswith("24,126 ")
    assert [tick["year"] for tick in fund["year_ticks"]] == [
        2016, 2018, 2020, 2022, 2024, 2025
    ]


@pytest.mark.parametrize(
    ("path", "title"),
    [
        ("/market/casino-industry/visitors", "연도별 카지노 이용객"),
        ("/market/casino-industry/revenue", "연도별 카지노 매출액 비율"),
        ("/market/casino-industry/fund", "기금 부과 현황"),
    ],
)
def test_casino_statistics_pages_are_public(client, path, title):
    response = client.get(path)
    assert response.status_code == 200
    assert title.encode() in response.data
    assert b"casino-interactive-chart" in response.data
    assert b"casino-chart-hitpoint" in response.data
    assert b"casino-chart-tooltip" in response.data
    assert b"casino-chart-area" in response.data
    assert b"linearGradient" in response.data
    assert b"js/casino-charts.js" in response.data

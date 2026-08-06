import pytest

from services import fund_increase_scenario


ROWS = [
    {"company_name": "파라다이스", "account_code": "121000", "fiscal_date": "2025-12-31", "amount": 400_000_000_000},
    {"company_name": "파라다이스", "account_code": "125000", "fiscal_date": "2025-12-31", "amount": 40_000_000_000},
    {"company_name": "GKL", "account_code": "121000", "fiscal_date": "2025-12-31", "amount": 300_000_000_000},
    {"company_name": "GKL", "account_code": "125000", "fiscal_date": "2025-12-31", "amount": 30_000_000_000},
    {"company_name": "인스파이어", "account_code": "121000", "fiscal_date": "2025-09-30", "amount": 350_000_000_000},
    {"company_name": "인스파이어", "account_code": "125000", "fiscal_date": "2025-09-30", "amount": -10_000_000_000},
    {"company_name": "파라다이스세가사미", "account_code": "121000", "fiscal_date": "2025-12-31", "amount": 500_000_000_000},
    {"company_name": "파라다이스세가사미", "account_code": "125000", "fiscal_date": "2025-12-31", "amount": 100_000_000_000},
    {"company_name": "롯데관광개발", "account_code": "121000", "fiscal_date": "2025-12-31", "amount": 276_000_000_000},
    {"company_name": "롯데관광개발", "account_code": "125000", "fiscal_date": "2025-12-31", "amount": -25_000_000_000},
]


def test_scenario_one_applies_incremental_five_percent_to_all_revenue(monkeypatch):
    monkeypatch.setattr(
        "services.fund_increase_scenario.queries.list_casino_market_share_financials",
        lambda connection, start_year, end_year: ROWS,
    )
    result = fund_increase_scenario.build_dashboard(object(), "1")
    paradise = next(item for item in result["items"] if item["company_name"] == "파라다이스")
    assert result["selected_scenario"] == "1"
    assert paradise["revenue"] == 4_000.0
    assert paradise["additional_fund"] == 200.0
    assert paradise["projected_profit"] == 200.0
    assert paradise["projected_margin"] == 5.0
    assert paradise["margin_change"] == -5.0
    assert result["available_count"] == 5
    lotte = next(item for item in result["items"] if item["company_name"] == "롯데관광개발")
    assert lotte["projected_profit"] == -388.0
    assert lotte["is_projected_loss"] is True


def test_scenario_two_only_applies_increase_above_3000_eok(monkeypatch):
    monkeypatch.setattr(
        "services.fund_increase_scenario.queries.list_casino_market_share_financials",
        lambda connection, start_year, end_year: ROWS,
    )
    result = fund_increase_scenario.build_dashboard(object(), "2")
    paradise = next(item for item in result["items"] if item["company_name"] == "파라다이스")
    gkl = next(item for item in result["items"] if item["company_name"] == "GKL")
    assert paradise["additional_fund"] == 50.0
    assert paradise["projected_profit"] == 350.0
    assert gkl["additional_fund"] == 0.0
    assert gkl["projected_profit"] == 300.0


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(tmp_path / "fund.db"))
    import app as app_module

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def test_fund_scenario_page_is_public(client, monkeypatch):
    monkeypatch.setattr(
        "app.fund_increase_scenario.build_dashboard",
        lambda connection, selected: {
            "base_year": 2025, "base_rate": 10, "proposed_rate": 15,
            "increase_rate": 5, "threshold_eok": 3000,
            "selected_scenario": "1", "items": [], "available_count": 0,
            "total_additional_fund": 0.0, "total_current_profit": 0.0,
            "total_projected_profit": 0.0,
        },
    )
    response = client.get("/laws/fund-increase-scenarios")
    assert response.status_code == 200
    assert "기금인상 시나리오".encode() in response.data
    assert b"SCENARIO 01" in response.data
    assert b"fund-scenario-tabs" in response.data

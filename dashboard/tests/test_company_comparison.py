import pytest

from services import company_comparison


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(tmp_path / "comparison.db"))
    import app as app_module

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def test_company_comparison_defaults_to_margin(monkeypatch):
    rows = [
        {"company_name": "파라다이스", "account_code": "121000", "fiscal_date": "2025-12-31", "amount": 100_000_000_000},
        {"company_name": "파라다이스", "account_code": "125000", "fiscal_date": "2025-12-31", "amount": 12_000_000_000},
        {"company_name": "인스파이어", "account_code": "121000", "fiscal_date": "2025-12-31", "amount": 80_000_000_000},
        {"company_name": "인스파이어", "account_code": "125000", "fiscal_date": "2025-12-31", "amount": -8_000_000_000},
    ]
    monkeypatch.setattr(
        "services.company_comparison.queries.list_casino_market_share_financials",
        lambda connection, start_year, end_year: rows,
    )
    result = company_comparison.build_dashboard(object())
    assert result["selected_year"] == 2025
    assert result["selected_metric"] == "margin"
    assert result["available_count"] == 2
    assert result["include_kangwon"] is False
    assert all(item["name"] != "강원랜드" for item in result["items"])
    assert result["items"][0]["name"] == "파라다이스"
    assert result["items"][0]["margin"] == 12.0
    inspire = next(item for item in result["items"] if item["name"] == "인스파이어")
    assert inspire["margin"] == -10.0
    assert inspire["is_negative"] is True
    assert result["zero_percent"] > 0


def test_company_comparison_metric_and_year_validation(monkeypatch):
    monkeypatch.setattr(
        "services.company_comparison.queries.list_casino_market_share_financials",
        lambda connection, start_year, end_year: [],
    )
    result = company_comparison.build_dashboard(object(), "2024", "revenue")
    assert result["selected_year"] == 2024
    assert result["selected_metric"] == "revenue"
    assert result["available_count"] == 0
    assert result["leader"] is None

    included = company_comparison.build_dashboard(
        object(), "2024", "revenue", include_kangwon=True
    )
    assert included["include_kangwon"] is True
    assert any(item["name"] == "강원랜드" for item in included["items"])


def test_company_comparison_page_is_public(client, monkeypatch):
    monkeypatch.setattr(
        "app.company_comparison.build_dashboard",
        lambda connection, year, metric, include_kangwon: {
            "years": [2025], "selected_year": 2025,
            "metrics": company_comparison.METRICS, "selected_metric": "margin",
            "metric": company_comparison.METRICS["margin"],
            "items": [{"name": "테스트 카지노", "revenue": 100.0,
                       "operating_profit": 10.0, "margin": 10.0,
                       "metric_value": 10.0, "is_negative": False,
                       "bar_left": 0, "bar_width": 100}],
            "zero_percent": 0, "available_count": 1,
            "leader": {"name": "테스트 카지노", "metric_value": 10.0},
            "median": 10.0,
            "include_kangwon": include_kangwon, "operator_count": 1,
        },
    )
    response = client.get("/companies/comparison")
    assert response.status_code == 200
    assert b"company-comparison-page" in response.data
    assert "영업이익률 비교".encode() in response.data
    assert b'name="metric" value="margin"' in response.data
    assert b'name="include_kangwon" value="1"' in response.data

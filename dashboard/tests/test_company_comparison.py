import pytest

from services import company_comparison


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(tmp_path / "comparison.db"))
    import app as app_module

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def _employment_rows():
    return [
        {"series_key": "employment.paradise.headcount", "value": 500,
         "observation_date": "2026-07-01"},
        {"series_key": "employment.paradise.headcount_growth_rate", "value": 5.0,
         "observation_date": "2026-07-01"},
    ]


def test_company_comparison_builds_profitability_and_workforce_metrics(monkeypatch):
    rows = [
        {"company_name": "파라다이스", "account_code": "121000", "fiscal_date": "2024-12-31", "period_type": "annual", "amount": 90_000_000_000},
        {"company_name": "파라다이스", "account_code": "121000", "fiscal_date": "2025-12-31", "period_type": "annual", "amount": 100_000_000_000},
        {"company_name": "파라다이스", "account_code": "124001", "fiscal_date": "2025-12-31", "period_type": "annual", "amount": 30_000_000_000},
        {"company_name": "파라다이스", "account_code": "125000", "fiscal_date": "2025-12-31", "period_type": "annual", "amount": 12_000_000_000},
        {"company_name": "인스파이어", "account_code": "121000", "fiscal_date": "2025-12-31", "period_type": "annual", "amount": 80_000_000_000},
        {"company_name": "인스파이어", "account_code": "125000", "fiscal_date": "2025-12-31", "period_type": "annual", "amount": -8_000_000_000},
    ]
    monkeypatch.setattr(
        "services.company_comparison.queries.list_casino_company_financials_by_period",
        lambda connection, start_year, end_year: rows,
    )
    monkeypatch.setattr(
        "services.company_comparison.queries.list_latest_company_employment_metrics",
        lambda connection: _employment_rows(),
    )
    result = company_comparison.build_dashboard(object())
    paradise = next(item for item in result["items"] if item["name"] == "파라다이스")
    assert paradise["margin"] == 12.0
    assert paradise["expense_ratio"] == 88.0
    assert paradise["personnel_cost_ratio"] == 30.0
    assert paradise["personnel_cost"] == 300.0
    assert paradise["revenue_per_employee"] == 200.0
    assert paradise["operating_profit_per_employee"] == 24.0
    assert paradise["revenue_growth"] == 11.1
    assert paradise["headcount_growth"] == 5.0
    assert paradise["growth_gap"] == 6.1
    assert paradise["headcount_date"] == "2026-07-01"
    assert result["selected_metric"] == "margin"
    assert result["available_count"] == 2
    assert all(item["name"] != "강원랜드" for item in result["items"])
    inspire = next(item for item in result["items"] if item["name"] == "인스파이어")
    assert inspire["margin"] == -10.0
    assert inspire["is_negative"] is True
    assert result["zero_percent"] > 0


def test_company_comparison_distinguishes_paradise_city_and_cost_order(monkeypatch):
    rows = [
        {"company_name": "파라다이스", "account_code": "121000", "fiscal_date": "2025-12-31", "period_type": "annual", "amount": 100_000_000_000},
        {"company_name": "파라다이스", "account_code": "125000", "fiscal_date": "2025-12-31", "period_type": "annual", "amount": 10_000_000_000},
        {"company_name": "파라다이스세가사미", "account_code": "121000", "fiscal_date": "2025-12-31", "period_type": "annual", "amount": 100_000_000_000},
        {"company_name": "파라다이스세가사미", "account_code": "125000", "fiscal_date": "2025-12-31", "period_type": "annual", "amount": 20_000_000_000},
    ]
    monkeypatch.setattr(
        "services.company_comparison.queries.list_casino_company_financials_by_period",
        lambda connection, start_year, end_year: rows,
    )
    monkeypatch.setattr(
        "services.company_comparison.queries.list_latest_company_employment_metrics",
        lambda connection: [],
    )
    result = company_comparison.build_dashboard(object(), "2025", "expense_ratio")
    assert result["items"][0]["name"] == "파라다이스시티(세가사미)"
    assert result["items"][0]["expense_ratio"] == 80.0
    assert result["leader_label"] == "최저 수치"


def test_company_comparison_metric_and_year_validation(monkeypatch):
    monkeypatch.setattr(
        "services.company_comparison.queries.list_casino_company_financials_by_period",
        lambda connection, start_year, end_year: [],
    )
    monkeypatch.setattr(
        "services.company_comparison.queries.list_latest_company_employment_metrics",
        lambda connection: [],
    )
    result = company_comparison.build_dashboard(object(), "2024", "revenue")
    assert result["selected_year"] == 2024
    assert result["selected_metric"] == "revenue"
    assert result["available_count"] == 0
    assert result["leader"] is None
    assert any(option["value"] == 2026 for option in result["year_options"])
    assert result["year_options"][-1] == {"value": 2026, "available": False}

    included = company_comparison.build_dashboard(
        object(), "2024", "revenue", include_kangwon=True
    )
    assert included["include_kangwon"] is True
    assert any(item["name"] == "강원랜드" for item in included["items"])


def test_company_comparison_page_is_public(client, monkeypatch):
    monkeypatch.setattr(
        "app.company_comparison.build_dashboard",
        lambda connection, year, metric, include_kangwon, period: {
            "years": [2025, 2026],
            "year_options": [
                {"value": 2025, "available": True},
                {"value": 2026, "available": False},
            ],
            "selected_year": 2025,
            "periods": company_comparison.PERIODS, "selected_period": "annual",
            "period_availability": {
                key: key == "annual" for key in company_comparison.PERIODS
            },
            "period": company_comparison.PERIODS["annual"],
            "metrics": company_comparison.METRICS, "selected_metric": "margin",
            "metric": company_comparison.METRICS["margin"],
            "items": [{"name": "테스트 카지노", "revenue": 100.0,
                       "operating_profit": 10.0, "personnel_cost": 20.0,
                       "margin": 10.0, "expense_ratio": 90.0,
                       "headcount": 100, "headcount_date": "2026-07-01",
                       "revenue_per_employee": 100.0,
                       "operating_profit_per_employee": 10.0,
                       "personnel_cost_ratio": 20.0, "revenue_growth": 5.0,
                       "headcount_growth": 2.0, "growth_gap": 3.0,
                       "metric_value": 10.0, "is_negative": False,
                       "bar_left": 0, "bar_width": 100}],
            "zero_percent": 0, "available_count": 1,
            "leader": {"name": "테스트 카지노", "metric_value": 10.0},
            "leader_label": "최고 수치", "median": 10.0,
            "include_kangwon": include_kangwon, "operator_count": 1,
        },
    )
    response = client.get("/companies/comparison")
    assert response.status_code == 200
    assert b"company-comparison-page" in response.data
    assert "총종업원급여".encode() in response.data
    assert "효율·구조 진단".encode() in response.data
    assert "인당 영업이익".encode() in response.data
    assert b'name="metric" value="margin"' in response.data
    assert b'name="include_kangwon" value="1"' in response.data
    assert "2026년 · 자료 없음".encode() in response.data
    assert response.data.count(b" disabled") >= 1


def test_company_comparison_defaults_to_latest_year_and_disables_empty_periods(monkeypatch):
    rows = [
        {"company_name": "GKL", "account_code": "121000",
         "fiscal_date": "2025-12-31", "period_type": "annual",
         "amount": 100_000_000_000},
        {"company_name": "GKL", "account_code": "121000",
         "fiscal_date": "2026-03-31", "period_type": "quarter_1",
         "amount": 30_000_000_000},
        {"company_name": "GKL", "account_code": "125000",
         "fiscal_date": "2026-03-31", "period_type": "quarter_1",
         "amount": 3_000_000_000},
    ]
    monkeypatch.setattr(
        "services.company_comparison.queries.list_casino_company_financials_by_period",
        lambda connection, start_year, end_year: rows,
    )
    monkeypatch.setattr(
        "services.company_comparison.queries.list_latest_company_employment_metrics",
        lambda connection: [],
    )

    result = company_comparison.build_dashboard(object())

    assert result["selected_year"] == 2026
    assert result["selected_period"] == "quarter_1"
    assert result["period_availability"]["quarter_1"] is True
    assert result["period_availability"]["annual"] is False
    assert result["year_options"][-1] == {"value": 2026, "available": True}


def test_company_comparison_derives_standalone_quarters(monkeypatch):
    rows = []
    period_values = {
        "quarter_1": (100, 10), "semiannual": (230, 25),
        "nine_month": (390, 45), "consolidated_annual": (550, 65),
    }
    dates = {
        "quarter_1": "2025-03-31", "semiannual": "2025-06-30",
        "nine_month": "2025-09-30", "consolidated_annual": "2025-12-31",
    }
    for period_type, (revenue, profit) in period_values.items():
        rows.extend([
            {"company_name": "GKL", "account_code": "121000",
             "fiscal_date": dates[period_type], "period_type": period_type,
             "amount": revenue * 100_000_000},
            {"company_name": "GKL", "account_code": "125000",
             "fiscal_date": dates[period_type], "period_type": period_type,
             "amount": profit * 100_000_000},
        ])
    monkeypatch.setattr(
        "services.company_comparison.queries.list_casino_company_financials_by_period",
        lambda connection, start_year, end_year: rows,
    )
    monkeypatch.setattr(
        "services.company_comparison.queries.list_latest_company_employment_metrics",
        lambda connection: [],
    )
    second = company_comparison.build_dashboard(
        object(), "2025", "revenue", False, "quarter_2"
    )
    third = company_comparison.build_dashboard(
        object(), "2025", "revenue", False, "quarter_3"
    )
    fourth = company_comparison.build_dashboard(
        object(), "2025", "revenue", False, "quarter_4"
    )
    second_half = company_comparison.build_dashboard(
        object(), "2025", "revenue", False, "second_half"
    )
    assert next(item for item in second["items"] if item["name"] == "GKL")["revenue"] == 130.0
    assert next(item for item in third["items"] if item["name"] == "GKL")["revenue"] == 160.0
    assert next(item for item in fourth["items"] if item["name"] == "GKL")["revenue"] == 160.0
    assert next(item for item in second_half["items"] if item["name"] == "GKL")["revenue"] == 320.0


def test_company_comparison_keeps_annual_and_consolidated_scopes_separate(monkeypatch):
    rows = [
        {"company_name": "롯데관광개발", "account_code": "121000",
         "fiscal_date": "2025-12-31", "period_type": "annual",
         "amount": 276_220_000_000},
        {"company_name": "롯데관광개발", "account_code": "125000",
         "fiscal_date": "2025-12-31", "period_type": "annual",
         "amount": -25_150_000_000},
        {"company_name": "롯데관광개발", "account_code": "121000",
         "fiscal_date": "2025-12-31", "period_type": "consolidated_annual",
         "amount": 653_450_000_000},
        {"company_name": "롯데관광개발", "account_code": "121000",
         "fiscal_date": "2025-06-30", "period_type": "semiannual",
         "amount": 300_000_000_000},
    ]
    monkeypatch.setattr(
        "services.company_comparison.queries.list_casino_company_financials_by_period",
        lambda connection, start_year, end_year: rows,
    )
    monkeypatch.setattr(
        "services.company_comparison.queries.list_latest_company_employment_metrics",
        lambda connection: [],
    )
    annual = company_comparison.build_dashboard(
        object(), "2025", "operating_profit", False, "annual"
    )
    second_half = company_comparison.build_dashboard(
        object(), "2025", "revenue", False, "second_half"
    )
    annual_lotte = next(item for item in annual["items"] if item["name"] == "롯데관광개발")
    half_lotte = next(item for item in second_half["items"] if item["name"] == "롯데관광개발")
    assert annual_lotte["operating_profit"] == -251.5
    assert half_lotte["revenue"] == 3534.5
    assert annual["period"]["scope"] == "운영법인 기준"
    assert second_half["period"]["label"] == "하반기(7~12월)"


def test_company_comparison_mobile_overflow_is_contained():
    from pathlib import Path

    css = (Path(__file__).parents[1] / "static" / "css" / "dashboard.css").read_text(
        encoding="utf-8"
    )
    assert ".company-comparison-page{min-width:0;max-width:1440px" in css
    assert ".company-comparison-page>*{min-width:0;max-width:100%" in css
    assert ".company-comparison-table-panel .table-scroll-wrap{overflow-x:auto" in css
    assert ".company-comparison-track{grid-column:1/-1;grid-row:2}" in css
    assert ".fund-scenario-page,.company-comparison-page{" not in css

"""Tourism fund increase scenarios based on central annual financial data."""

from __future__ import annotations

from dashboard_db import queries


BASE_RATE = 0.10
PROPOSED_RATE = 0.15
INCREASE_RATE = PROPOSED_RATE - BASE_RATE
THRESHOLD_EOK = 3_000.0
BASE_YEAR = 2025

COMPANIES = (
    ("파라다이스", "파라다이스"),
    ("GKL", "GKL"),
    ("인스파이어", "인스파이어"),
    ("파라다이스세가사미", "파라다이스시티"),
    ("롯데관광개발", "롯데관광개발"),
)


def _eok(value):
    return round(value / 100_000_000, 1) if value is not None else None


def _margin(profit, revenue):
    if revenue in (None, 0) or profit is None:
        return None
    return round(profit / revenue * 100, 1)


def build_dashboard(connection, selected_scenario=None):
    """Return both scenarios and the selected operator comparison."""

    scenario_key = "2" if str(selected_scenario) == "2" else "1"
    values = {}
    for row in queries.list_casino_market_share_financials(
        connection, BASE_YEAR, BASE_YEAR
    ):
        company = row["company_name"]
        if company not in dict(COMPANIES):
            continue
        metric = (
            "revenue" if row["account_code"] == "121000" else "operating_profit"
        )
        values.setdefault(company, {})[metric] = _eok(row["amount"])
        values[company]["fiscal_date"] = row["fiscal_date"]

    items = []
    for company_name, display_name in COMPANIES:
        financials = values.get(company_name, {})
        revenue = financials.get("revenue")
        operating_profit = financials.get("operating_profit")
        if revenue is None or operating_profit is None:
            items.append({
                "company_name": company_name,
                "display_name": display_name,
                "available": False,
                "fiscal_date": financials.get("fiscal_date"),
            })
            continue

        ggr = revenue / (1 - BASE_RATE)
        scenario_base = ggr if scenario_key == "1" else max(ggr - THRESHOLD_EOK, 0)
        legacy_base = revenue if scenario_key == "1" else max(revenue - THRESHOLD_EOK, 0)
        additional_fund = round(scenario_base * INCREASE_RATE, 1)
        legacy_additional_fund = round(legacy_base * INCREASE_RATE, 1)
        projected_revenue = round(revenue - additional_fund, 1)
        projected_profit = round(operating_profit - additional_fund, 1)
        legacy_projected_profit = round(
            operating_profit - legacy_additional_fund, 1
        )
        current_margin = _margin(operating_profit, revenue)
        projected_margin = _margin(projected_profit, projected_revenue)
        items.append({
            "company_name": company_name,
            "display_name": display_name,
            "available": True,
            "fiscal_date": financials.get("fiscal_date"),
            "revenue": revenue,
            "operating_profit": operating_profit,
            "current_margin": current_margin,
            "ggr": round(ggr, 1),
            "scenario_base": round(scenario_base, 1),
            "additional_fund": additional_fund,
            "legacy_additional_fund": legacy_additional_fund,
            "additional_fund_difference": round(
                additional_fund - legacy_additional_fund, 1
            ),
            "projected_revenue": projected_revenue,
            "projected_profit": projected_profit,
            "legacy_projected_profit": legacy_projected_profit,
            "projected_margin": projected_margin,
            "margin_change": (
                round(projected_margin - current_margin, 1)
                if current_margin is not None and projected_margin is not None
                else None
            ),
            "is_projected_loss": projected_profit < 0,
        })

    available = [item for item in items if item.get("available")]
    max_profit = max(
        [abs(item["operating_profit"]) for item in available]
        + [abs(item["projected_profit"]) for item in available]
        + [1]
    )
    for item in available:
        item["current_bar_width"] = round(abs(item["operating_profit"]) / max_profit * 100, 2)
        item["projected_bar_width"] = round(abs(item["projected_profit"]) / max_profit * 100, 2)

    return {
        "base_year": BASE_YEAR,
        "base_rate": int(BASE_RATE * 100),
        "proposed_rate": int(PROPOSED_RATE * 100),
        "increase_rate": int(INCREASE_RATE * 100),
        "threshold_eok": int(THRESHOLD_EOK),
        "selected_scenario": scenario_key,
        "items": items,
        "available_count": len(available),
        "total_additional_fund": round(
            sum(item["additional_fund"] for item in available), 1
        ),
        "total_legacy_additional_fund": round(
            sum(item["legacy_additional_fund"] for item in available), 1
        ),
        "total_additional_fund_difference": round(
            sum(item["additional_fund_difference"] for item in available), 1
        ),
        "total_current_profit": round(
            sum(item["operating_profit"] for item in available), 1
        ),
        "total_projected_profit": round(
            sum(item["projected_profit"] for item in available), 1
        ),
    }

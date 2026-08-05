"""Casino-operator financial comparison built from the central statement store."""

from __future__ import annotations

from statistics import median

from dashboard_db import queries


COMPANIES = (
    ("강원랜드", "강원랜드"),
    ("파라다이스", "파라다이스"),
    ("파라다이스세가사미", "파라다이스세가사미"),
    ("GKL", "GKL"),
    ("인스파이어", "인스파이어"),
    ("롯데관광개발", "롯데관광개발"),
)

METRICS = {
    "margin": {"label": "영업이익률", "unit": "%"},
    "revenue": {"label": "매출액", "unit": "억원"},
    "operating_profit": {"label": "영업이익", "unit": "억원"},
}


def _eok(value):
    return round(value / 100_000_000, 1) if value is not None else None


def _chart_geometry(items):
    present = [item["metric_value"] for item in items if item["metric_value"] is not None]
    low = min([0, *present])
    high = max([0, *present])
    span = max(high - low, 1)
    zero = round((0 - low) / span * 100, 3)
    for item in items:
        value = item["metric_value"]
        if value is None:
            item.update({"bar_left": zero, "bar_width": 0})
            continue
        position = (value - low) / span * 100
        item.update({
            "bar_left": round(min(zero, position), 3),
            "bar_width": round(abs(position - zero), 3),
        })
    return zero


def build_dashboard(connection, selected_year=None, selected_metric=None):
    years = [2023, 2024, 2025]
    try:
        selected_year = int(selected_year)
    except (TypeError, ValueError):
        selected_year = years[-1]
    if selected_year not in years:
        selected_year = years[-1]
    selected_metric = selected_metric if selected_metric in METRICS else "margin"

    values = {}
    company_names = dict(COMPANIES)
    for row in queries.list_casino_market_share_financials(
        connection, years[0], years[-1]
    ):
        company = row["company_name"]
        if company not in company_names:
            continue
        year = int(str(row["fiscal_date"])[:4])
        metric = "revenue" if row["account_code"] == "121000" else "operating_profit"
        values.setdefault((company, year), {})[metric] = _eok(row["amount"])

    items = []
    for company, label in COMPANIES:
        financials = values.get((company, selected_year), {})
        revenue = financials.get("revenue")
        operating_profit = financials.get("operating_profit")
        margin = (
            round(operating_profit / revenue * 100, 1)
            if revenue not in (None, 0) and operating_profit is not None
            else None
        )
        metric_value = {
            "margin": margin,
            "revenue": revenue,
            "operating_profit": operating_profit,
        }[selected_metric]
        items.append({
            "name": label,
            "revenue": revenue,
            "operating_profit": operating_profit,
            "margin": margin,
            "metric_value": metric_value,
            "is_negative": metric_value is not None and metric_value < 0,
        })

    items.sort(
        key=lambda item: (
            item["metric_value"] is not None,
            item["metric_value"] if item["metric_value"] is not None else float("-inf"),
        ),
        reverse=True,
    )
    zero_percent = _chart_geometry(items)
    present = [item for item in items if item["metric_value"] is not None]
    values_for_summary = [item["metric_value"] for item in present]
    return {
        "years": years,
        "selected_year": selected_year,
        "metrics": METRICS,
        "selected_metric": selected_metric,
        "metric": METRICS[selected_metric],
        "items": items,
        "zero_percent": zero_percent,
        "available_count": len(present),
        "leader": present[0] if present else None,
        "median": round(median(values_for_summary), 1) if values_for_summary else None,
    }

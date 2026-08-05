"""Casino market-share views built from the central financial statement store."""

from __future__ import annotations

from dashboard_db import queries


COMPANY_SEGMENTS = {
    "강원랜드": ("domestic", "강원랜드"),
    "파라다이스": ("mainland", "파라다이스"),
    "파라다이스세가사미": ("mainland", "파라다이스세가사미"),
    "GKL": ("mainland", "GKL"),
    "인스파이어": ("mainland", "인스파이어"),
    "롯데관광개발": ("jeju", "롯데관광개발"),
}


def _amount(value):
    return round((value or 0) / 100_000_000, 1)


def _with_share(items, key):
    total = sum(max(item[key], 0) for item in items)
    return [
        {**item, "share": round(max(item[key], 0) / total * 100, 1) if total else 0}
        for item in items
    ]


def build_dashboard(connection, selected_year=None, exclude_kangwon=False):
    years = [2023, 2024, 2025]
    try:
        selected_year = int(selected_year)
    except (TypeError, ValueError):
        selected_year = years[-1]
    if selected_year not in years:
        selected_year = years[-1]

    values = {}
    for row in queries.list_casino_market_share_financials(connection, 2021, 2025):
        company = row["company_name"]
        if company not in COMPANY_SEGMENTS:
            continue
        year = int(row["fiscal_date"][:4])
        metric = "revenue" if row["account_code"] == "121000" else "operating_profit"
        values.setdefault((company, year), {})[metric] = _amount(row["amount"])

    companies = []
    for company, (segment, label) in COMPANY_SEGMENTS.items():
        metrics = values.get((company, selected_year), {})
        if metrics:
            companies.append({
                "name": label,
                "segment": segment,
                "revenue": metrics.get("revenue", 0),
                "operating_profit": metrics.get("operating_profit", 0),
            })

    def aggregate(name, members):
        return {
            "name": name,
            "revenue": round(sum(item["revenue"] for item in members), 1),
            "operating_profit": round(sum(item["operating_profit"] for item in members), 1),
        }

    foreign = [item for item in companies if item["segment"] != "domestic"]
    domestic = [item for item in companies if item["segment"] == "domestic"]
    mainland = [item for item in foreign if item["segment"] == "mainland"]
    jeju = [item for item in foreign if item["segment"] == "jeju"]
    comparisons = [
        {"title": "전체 시장", "subtitle": "외래객 카지노 운영사 vs 내국인 카지노 운영사", "items": [aggregate("외래객", foreign), aggregate("내국인", domestic)]},
        {"title": "외래객 카지노", "subtitle": "육지 운영사 vs 제주 운영사", "items": [aggregate("육지", mainland), aggregate("제주", jeju)]},
        {"title": "육지 외래객 카지노", "subtitle": "주요 운영 법인별 비교", "items": mainland},
    ]
    for comparison in comparisons:
        comparison["revenue_items"] = _with_share(comparison["items"], "revenue")
        comparison["profit_items"] = _with_share(comparison["items"], "operating_profit")

    trend_years = list(range(2021, 2026))
    trend = []
    for company, (_, label) in COMPANY_SEGMENTS.items():
        points = []
        for year in trend_years:
            metrics = values.get((company, year), {})
            points.append({"year": year, "revenue": metrics.get("revenue"), "operating_profit": metrics.get("operating_profit")})
        if any(point["revenue"] is not None for point in points):
            trend.append({"name": label, "points": points})

    if exclude_kangwon:
        trend = [item for item in trend if item["name"] != "강원랜드"]

    for metric in ("revenue", "operating_profit"):
        present = [point[metric] for item in trend for point in item["points"] if point[metric] is not None]
        low, high = min(present or [0]), max(present or [1])
        span = max(high - low, 1)
        for item in trend:
            chart_points = [
                {
                    "year": point["year"],
                    "value": point[metric],
                    "x": round(24 + index * 188, 1),
                    "y": round(216 - (point[metric] - low) / span * 184, 1),
                }
                for index, point in enumerate(item["points"])
                if point[metric] is not None
            ]
            item[f"{metric}_chart_points"] = chart_points
            item[f"{metric}_polyline"] = " ".join(
                f'{point["x"]:.1f},{point["y"]:.1f}' for point in chart_points
            )

    return {
        "years": years,
        "selected_year": selected_year,
        "comparisons": comparisons,
        "trend_years": trend_years,
        "trend": trend,
        "exclude_kangwon": bool(exclude_kangwon),
    }

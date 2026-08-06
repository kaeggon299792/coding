"""Casino-operator financial and workforce comparison from the central store."""

from __future__ import annotations

from statistics import median

from dashboard_db import queries


COMPANIES = (
    ("강원랜드", "강원랜드", "kangwon_land"),
    ("파라다이스", "파라다이스", "paradise"),
    ("파라다이스세가사미", "파라다이스시티(세가사미)", "paradise_segasammy"),
    ("GKL", "GKL", "gkl"),
    ("인스파이어", "인스파이어", "inspire"),
    ("롯데관광개발", "롯데관광개발", "lotte_tour"),
)

METRICS = {
    "margin": {
        "label": "영업이익률", "unit": "%", "group": "수익성",
        "description": "매출에서 영업이익이 차지하는 비율입니다. 높을수록 본업 수익성이 좋습니다.",
    },
    "expense_ratio": {
        "label": "영업비용률", "unit": "%", "group": "비용 효율",
        "description": "매출 중 영업비용이 차지하는 비율입니다. 낮을수록 비용 효율이 좋습니다.",
        "lower_is_better": True,
    },
    "revenue_per_employee": {
        "label": "인당 매출", "unit": "백만원", "group": "인력 효율",
        "description": "선택 기간 매출을 국민연금 최신 가입자수로 나눈 값입니다.",
    },
    "operating_profit_per_employee": {
        "label": "인당 영업이익", "unit": "백만원", "group": "인력 효율",
        "description": "선택 기간 영업이익을 국민연금 최신 가입자수로 나눈 값입니다.",
    },
    "personnel_cost_ratio": {
        "label": "인건비율", "unit": "%", "group": "인력 부담",
        "description": "손익계산서의 총종업원급여가 매출에서 차지하는 비율입니다. 낮을수록 부담이 작습니다.",
        "lower_is_better": True,
    },
    "growth_gap": {
        "label": "매출·인원 증가율 차이", "unit": "%p", "group": "구조 진단",
        "description": "전년 대비 매출 증가율에서 국민연금 인원 증가율을 뺀 값입니다. 양수면 매출이 인원보다 빠르게 늘었습니다.",
    },
    "revenue": {
        "label": "매출액", "unit": "억원", "group": "손익",
        "description": "선택 연도의 법인별 연간 매출액입니다.",
    },
    "operating_profit": {
        "label": "영업이익", "unit": "억원", "group": "손익",
        "description": "선택 연도의 법인별 연간 영업이익입니다.",
    },
}

PERIODS = {
    "annual": {"label": "연간", "source": "annual", "scope": "운영법인 기준"},
    "semiannual": {
        "label": "상반기(1~6월 누계)", "source": "semiannual", "scope": "연결 기준",
    },
    "second_half": {
        "label": "하반기(7~12월)",
        "subtract": ("consolidated_annual", "semiannual"),
        "scope": "연결 기준",
    },
    "quarter_1": {"label": "1분기", "source": "quarter_1", "scope": "연결 기준"},
    "quarter_2": {
        "label": "2분기", "subtract": ("semiannual", "quarter_1"), "scope": "연결 기준",
    },
    "quarter_3": {
        "label": "3분기", "subtract": ("nine_month", "semiannual"), "scope": "연결 기준",
    },
    "quarter_4": {
        "label": "4분기", "subtract": ("consolidated_annual", "nine_month"),
        "scope": "연결 기준",
    },
}

ACCOUNT_METRICS = {
    "121000": "revenue",
    "124001": "personnel_cost",
    "125000": "operating_profit",
}


def _eok(value):
    return round(value / 100_000_000, 1) if value is not None else None


def _ratio(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    return round(numerator / denominator * 100, 1)


def _latest_employment(connection):
    values = {}
    for row in queries.list_latest_company_employment_metrics(connection):
        parts = row["series_key"].split(".", 2)
        if len(parts) != 3:
            continue
        entity = values.setdefault(parts[1], {"observation_date": row["observation_date"]})
        if row["observation_date"] >= entity["observation_date"]:
            entity["observation_date"] = row["observation_date"]
        if parts[2] == "headcount":
            entity["headcount"] = row["value"]
        elif parts[2] == "headcount_growth_rate":
            entity["headcount_growth"] = row["value"]
    return values


def _period_financials(values, company, year, period_key):
    period = PERIODS[period_key]
    if "source" in period:
        return dict(values.get((company, year, period["source"]), {}))
    later_key, earlier_key = period["subtract"]
    later = values.get((company, year, later_key), {})
    earlier = values.get((company, year, earlier_key), {})
    result = {}
    for metric in ACCOUNT_METRICS.values():
        if later.get(metric) is not None and earlier.get(metric) is not None:
            result[metric] = round(later[metric] - earlier[metric], 1)
    return result


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


def build_dashboard(
    connection, selected_year=None, selected_metric=None, include_kangwon=False,
    selected_period=None,
):
    selected_period = selected_period if selected_period in PERIODS else "annual"
    selected_metric = selected_metric if selected_metric in METRICS else "margin"

    values = {}
    company_names = {company for company, _label, _entity in COMPANIES}
    for row in queries.list_casino_company_financials_by_period(
        connection, 2023, 2026
    ):
        company = row["company_name"]
        metric = ACCOUNT_METRICS.get(str(row["account_code"]))
        if company not in company_names or not metric:
            continue
        year = int(str(row["fiscal_date"])[:4])
        values.setdefault((company, year, row["period_type"]), {})[metric] = _eok(
            row["amount"]
        )

    years = sorted({
        year for company, _label, _entity in COMPANIES for year in range(2023, 2027)
        if _period_financials(values, company, year, selected_period).get("revenue")
        is not None
    }) or [2023, 2024, 2025]
    try:
        selected_year = int(selected_year)
    except (TypeError, ValueError):
        selected_year = years[-1]
    if selected_year not in years:
        selected_year = years[-1]

    employment = _latest_employment(connection)
    items = []
    for company, label, entity_code in COMPANIES:
        if company == "강원랜드" and not include_kangwon:
            continue
        financials = _period_financials(values, company, selected_year, selected_period)
        previous = _period_financials(
            values, company, selected_year - 1, selected_period
        )
        workforce = employment.get(entity_code, {})
        revenue = financials.get("revenue")
        operating_profit = financials.get("operating_profit")
        personnel_cost = financials.get("personnel_cost")
        headcount = workforce.get("headcount")
        margin = _ratio(operating_profit, revenue)
        expense_ratio = (
            round((revenue - operating_profit) / revenue * 100, 1)
            if revenue not in (None, 0) and operating_profit is not None else None
        )
        revenue_growth = (
            round((revenue / previous["revenue"] - 1) * 100, 1)
            if revenue is not None and previous.get("revenue") not in (None, 0) else None
        )
        headcount_growth = workforce.get("headcount_growth")
        growth_gap = (
            round(revenue_growth - headcount_growth, 1)
            if revenue_growth is not None and headcount_growth is not None else None
        )
        item = {
            "name": label,
            "revenue": revenue,
            "operating_profit": operating_profit,
            "personnel_cost": personnel_cost,
            "margin": margin,
            "expense_ratio": expense_ratio,
            "headcount": round(headcount) if headcount is not None else None,
            "headcount_date": workforce.get("observation_date"),
            "revenue_per_employee": (
                round(revenue * 100 / headcount, 1)
                if revenue is not None and headcount not in (None, 0) else None
            ),
            "operating_profit_per_employee": (
                round(operating_profit * 100 / headcount, 1)
                if operating_profit is not None and headcount not in (None, 0) else None
            ),
            "personnel_cost_ratio": _ratio(personnel_cost, revenue),
            "revenue_growth": revenue_growth,
            "headcount_growth": headcount_growth,
            "growth_gap": growth_gap,
        }
        item["metric_value"] = item[selected_metric]
        item["is_negative"] = item["metric_value"] is not None and item["metric_value"] < 0
        items.append(item)

    lower_is_better = METRICS[selected_metric].get("lower_is_better", False)
    items.sort(key=lambda item: (
        item["metric_value"] is None,
        item["metric_value"] if lower_is_better else -(item["metric_value"] or 0),
    ))
    zero_percent = _chart_geometry(items)
    present = [item for item in items if item["metric_value"] is not None]
    values_for_summary = [item["metric_value"] for item in present]
    return {
        "years": years,
        "selected_year": selected_year,
        "periods": PERIODS,
        "selected_period": selected_period,
        "period": PERIODS[selected_period],
        "metrics": METRICS,
        "selected_metric": selected_metric,
        "metric": METRICS[selected_metric],
        "items": items,
        "zero_percent": zero_percent,
        "available_count": len(present),
        "leader": present[0] if present else None,
        "leader_label": "최저 수치" if lower_is_better else "최고 수치",
        "median": round(median(values_for_summary), 1) if values_for_summary else None,
        "include_kangwon": bool(include_kangwon),
        "operator_count": len(items),
    }

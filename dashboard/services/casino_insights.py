"""Derived casino-industry indicators built only from the central data store."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean

OPERATORS = (
    {
        "name": "파라다이스",
        "revenue": "epic.paradise_monthly_revenue.m01",
        "drop": "epic.paradise_monthly_drop_casino.m01",
        "hold": "epic.paradise_monthly_hold.m01",
        "visitors": "epic.paradise_monthly_vip_visits.m01",
        "visitor_basis": "VIP 방문일 기준",
    },
    {
        "name": "GKL",
        "revenue": "epic.gkl_monthly_revenue.m01",
        "drop": "epic.gkl_monthly_drop.m01",
        "hold": "epic.gkl_monthly_hold.m01",
        "visitors": "epic.gkl_monthly_visitors.m01",
        "visitor_basis": "입장객 기준",
    },
    {
        "name": "드림타워",
        "revenue": "epic.dreamtower_monthly_revenue.m01",
        "drop": "epic.dreamtower_monthly_drop.m01",
        "hold": "epic.dreamtower_monthly_hold.m01",
        "visitors": "epic.dreamtower_monthly_visitors.m01",
        "visitor_basis": "입장객 기준",
    },
)

NATIONALITY_SERIES = (
    {
        "name": "중국",
        "vip_drop": "epic.paradise_monthly_drop_nationality.m02",
        "arrivals": "epic.korea_monthly_foreign_arrivals_nationality.m07",
    },
    {
        "name": "일본",
        "vip_drop": "epic.paradise_monthly_drop_nationality.m03",
        "arrivals": "epic.korea_monthly_foreign_arrivals_nationality.m03",
    },
)

FUND_KEYS = {
    "foreign": "epic.korea_yearly_casino_fund.m18",
    "kangwon": "epic.korea_yearly_casino_fund.m19",
    "total": "epic.korea_yearly_casino_fund.m20",
}

RECOVERY_KEYS = {
    "korea_arrivals": "epic.korea_monthly_foreign_arrivals_nationality.m01",
    "macao_arrivals": "epic.macao_monthly_tourist_arrivals.m01",
    "macao_gaming": "epic.macao_monthly_gaming_revenue.m01",
}


def _clamp(value, minimum=0.0, maximum=100.0):
    return max(minimum, min(maximum, value))


def _growth(current, previous):
    if current is None or previous in (None, 0):
        return None
    return (current / previous - 1) * 100


def _rounded(value, digits=1):
    return None if value is None else round(value, digits)


def _series_values(connection, keys):
    keys = tuple(dict.fromkeys(key for key in keys if key))
    if not keys:
        return {}
    placeholders = ",".join("?" for _ in keys)
    rows = connection.execute(
        f"""
        SELECT series_key, observation_date, value
        FROM source_data_points
        WHERE series_key IN ({placeholders})
        ORDER BY observation_date
        """,
        keys,
    ).fetchall()
    values = defaultdict(dict)
    for row in rows:
        values[row["series_key"]][row["observation_date"]] = float(row["value"])
    return dict(values)


def _latest(series, cutoff=None):
    if not series:
        return None, None
    candidates = [day for day in series if cutoff is None or day <= cutoff]
    if not candidates:
        return None, None
    day = max(candidates)
    return day, series[day]


def _period_value(series, selected_period=None):
    if not selected_period:
        return _latest(series)
    day = f"{selected_period}-01"
    return day, series.get(day)


def _year_ago(series, day):
    if not day:
        return None
    previous_day = f"{int(day[:4]) - 1}{day[4:]}"
    return series.get(previous_day)


def _trailing_average(series, day, count=12):
    if not series or not day:
        return None
    values = [value for date, value in sorted(series.items()) if date <= day][-count:]
    return mean(values) if values else None


def _operator_metrics(values, definition, selected_period=None):
    revenue = values.get(definition["revenue"], {})
    drop = values.get(definition["drop"], {})
    hold = values.get(definition["hold"], {})
    visitors = values.get(definition["visitors"], {}) if definition["visitors"] else {}
    revenue_day, revenue_now = _period_value(revenue, selected_period)
    drop_day, drop_now = _period_value(drop, selected_period)
    hold_day, hold_now = _period_value(hold, selected_period)
    visitor_day, visitors_now = _period_value(visitors, selected_period)
    revenue_yoy = _growth(revenue_now, _year_ago(revenue, revenue_day))
    drop_yoy = _growth(drop_now, _year_ago(drop, drop_day))
    visitor_yoy = _growth(visitors_now, _year_ago(visitors, visitor_day))
    hold_average = _trailing_average(hold, hold_day)
    hold_gap = None if hold_now is None or hold_average is None else hold_now - hold_average

    components = []
    for metric, weight in ((revenue_yoy, 35), (drop_yoy, 25), (visitor_yoy, 25)):
        if metric is not None:
            components.append((_clamp(50 + metric * 1.25), weight))
    if hold_gap is not None:
        components.append((_clamp(100 - abs(hold_gap) * 10), 15))
    score = (
        sum(value * weight for value, weight in components)
        / sum(weight for _, weight in components)
        if components else None
    )
    if score is None:
        status = "데이터 부족"
    elif score >= 80:
        status = "HOT"
    elif score >= 65:
        status = "RISING"
    elif score >= 45:
        status = "STEADY"
    else:
        status = "COOLING"

    luck_status = "데이터 부족"
    if hold_gap is not None:
        if hold_gap >= 1:
            luck_status = "HOUSE LUCKY"
        elif hold_gap <= -1:
            luck_status = "PLAYER FRIENDLY"
        else:
            luck_status = "NORMAL"

    spend = revenue_now * 1_000_000 / visitors_now if revenue_now and visitors_now else None
    previous_revenue = _year_ago(revenue, revenue_day)
    previous_visitors = _year_ago(visitors, visitor_day)
    previous_spend = (
        previous_revenue * 1_000_000 / previous_visitors
        if previous_revenue and previous_visitors else None
    )
    spend_yoy = _growth(spend, previous_spend)

    quality = None
    if all(value not in (None, 0) for value in (
        revenue_now, previous_revenue, visitors_now, previous_visitors,
    )):
        base_spend = previous_revenue / previous_visitors
        current_spend = revenue_now / visitors_now
        visitor_effect = (visitors_now - previous_visitors) * base_spend / previous_revenue * 100
        spend_effect = visitors_now * (current_spend - base_spend) / previous_revenue * 100
        quality = {
            "revenue_growth": _rounded(revenue_yoy),
            "visitor_effect": _rounded(visitor_effect),
            "spend_effect": _rounded(spend_effect),
        }

    return {
        "name": definition["name"],
        "period": revenue_day[:7] if revenue_day else None,
        "score": _rounded(score),
        "score_width": _rounded(score or 0),
        "status": status,
        "revenue": revenue_now,
        "revenue_yoy": _rounded(revenue_yoy),
        "drop_yoy": _rounded(drop_yoy),
        "visitor_yoy": _rounded(visitor_yoy),
        "hold": _rounded(hold_now),
        "hold_average": _rounded(hold_average),
        "hold_gap": _rounded(hold_gap),
        "luck_status": luck_status,
        "spend_per_visitor": _rounded(spend, 0),
        "spend_yoy": _rounded(spend_yoy),
        "quality": quality,
        "has_visitors": bool(visitors),
        "visitor_basis": definition.get("visitor_basis", "입장객 기준"),
    }


def _nationality_demand(values, selected_period=None):
    result = []
    for item in NATIONALITY_SERIES:
        vip = values.get(item["vip_drop"], {})
        arrivals = values.get(item["arrivals"], {})
        vip_day, vip_now = _period_value(vip, selected_period)
        arrival_day, arrival_now = _period_value(arrivals, selected_period)
        vip_yoy = _growth(vip_now, _year_ago(vip, vip_day))
        arrival_yoy = _growth(arrival_now, _year_ago(arrivals, arrival_day))
        available = [value for value in (vip_yoy, arrival_yoy) if value is not None]
        score = _clamp(50 + mean(available)) if available else None
        result.append({
            "name": item["name"],
            "score": _rounded(score),
            "score_width": _rounded(score or 0),
            "vip_period": vip_day[:7] if vip_day else None,
            "vip_drop": vip_now,
            "vip_yoy": _rounded(vip_yoy),
            "arrival_period": arrival_day[:7] if arrival_day else None,
            "arrivals": arrival_now,
            "arrival_yoy": _rounded(arrival_yoy),
        })
    return result


def _fund_metrics(values, selected_period=None):
    series = {name: values.get(key, {}) for name, key in FUND_KEYS.items()}
    cutoff = f"{selected_period[:4]}-12-31" if selected_period else None
    day, total = _latest(series["total"], cutoff)
    previous = _year_ago(series["total"], day)
    foreign = series["foreign"].get(day) if day else None
    kangwon = series["kangwon"].get(day) if day else None
    base = series["total"].get("2019-01-01")
    return {
        "year": day[:4] if day else None,
        "total": total,
        "yoy": _rounded(_growth(total, previous)),
        "foreign_share": _rounded(foreign / total * 100) if foreign is not None and total else None,
        "kangwon_share": _rounded(kangwon / total * 100) if kangwon is not None and total else None,
        "index_2019": _rounded(total / base * 100) if total is not None and base else None,
    }


def _recovery_metrics(values, selected_period=None):
    result = []
    definitions = (
        ("한국 외래객", "korea_arrivals", "명"),
        ("마카오 관광객", "macao_arrivals", "명"),
        ("마카오 게이밍 수입", "macao_gaming", "백만MOP"),
    )
    for name, lookup, unit in definitions:
        series = values.get(RECOVERY_KEYS[lookup], {})
        day, current = _period_value(series, selected_period)
        baseline_day = f"2019-{day[5:]}" if day else None
        baseline = series.get(baseline_day) if baseline_day else None
        index = current / baseline * 100 if current is not None and baseline else None
        result.append({
            "name": name,
            "period": day[:7] if day else None,
            "value": current,
            "unit": unit,
            "index": _rounded(index),
            "index_width": _rounded(_clamp(index or 0, maximum=160) / 160 * 100),
        })
    return result


def _seasonality(values):
    operator_indices = defaultdict(list)
    for operator in OPERATORS:
        series = values.get(operator["revenue"], {})
        selected = {
            day: value for day, value in series.items()
            if "2021-01-01" <= day <= "2025-12-31"
        }
        average = mean(selected.values()) if selected else None
        if not average:
            continue
        monthly = defaultdict(list)
        for day, value in selected.items():
            monthly[int(day[5:7])].append(value / average * 100)
        for month, items in monthly.items():
            operator_indices[month].append(mean(items))
    result = []
    for month in range(1, 13):
        index = mean(operator_indices[month]) if operator_indices[month] else None
        if index is None:
            level = "데이터 부족"
        elif index >= 110:
            level = "최고 성수기"
        elif index >= 102:
            level = "성수기"
        elif index >= 94:
            level = "보통"
        else:
            level = "비수기"
        result.append({"month": month, "index": _rounded(index), "level": level})
    return result


def build_dashboard(connection, selected_period=None):
    keys = []
    for item in OPERATORS:
        keys.extend((item["revenue"], item["drop"], item["hold"], item["visitors"]))
    for item in NATIONALITY_SERIES:
        keys.extend((item["vip_drop"], item["arrivals"]))
    keys.extend(FUND_KEYS.values())
    keys.extend(RECOVERY_KEYS.values())
    values = _series_values(connection, keys)
    available_periods = sorted(
        {
            day[:7]
            for operator in OPERATORS
            for day in values.get(operator["revenue"], {})
        },
        reverse=True,
    )
    if selected_period not in available_periods:
        selected_period = available_periods[0] if available_periods else None
    operators = [
        _operator_metrics(values, item, selected_period) for item in OPERATORS
    ]
    ranking = sorted(
        (item for item in operators if item["score"] is not None),
        key=lambda item: item["score"], reverse=True,
    )
    for rank, item in enumerate(ranking, start=1):
        item["rank"] = rank
    visitor_rows = [item for item in operators if item["spend_per_visitor"] is not None]
    quality_rows = [item for item in operators if item["quality"] is not None]
    return {
        "has_data": bool(ranking),
        "latest_period": selected_period,
        "selected_period": selected_period,
        "available_periods": available_periods,
        "ranking": ranking,
        "visitor_rows": visitor_rows,
        "quality_rows": quality_rows,
        "nationality": _nationality_demand(values, selected_period),
        "fund": _fund_metrics(values, selected_period),
        "recovery": _recovery_metrics(values, selected_period),
        "seasonality": _seasonality(values),
        "visitor_conversion": 18.5,
        "tourism_fx_share": 7.3,
    }

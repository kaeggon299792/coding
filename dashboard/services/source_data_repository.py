"""CASINO IN 숫자 데이터의 중앙 누적·조회 서비스."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta

from dashboard_db import queries
from services import casino_industry, casino_statistics
from utils import now_kst


BACKFILL_STATE_KEY = "source_repository_backfill_v1"
ALLOWED_GRAINS = {"daily", "monthly", "yearly"}


def _date(value):
    text = str(value or "").strip().replace(".", "-").replace("/", "-")
    if len(text) == 6 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-01"
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text[:10]


def _series(connection, key, category, label, unit, frequency, aggregation, source, *, internal=False, url=None):
    queries.upsert_source_data_series(
        connection, series_key=key, category=category, label=label, unit=unit,
        frequency=frequency, aggregation=aggregation, source_name=source,
        source_url=url, is_internal=internal,
    )


def _point(connection, key, observation_date, value, record_key=None):
    if value is not None:
        queries.upsert_source_data_point(
            connection, series_key=key, observation_date=_date(observation_date),
            value=value, source_record_key=record_key,
        )


def _seed_static_statistics(connection):
    visitor_defs = (
        ("casino.yearly.foreign_visitors", "외래 방한객", "명", 1),
        ("casino.yearly.casino_visitors", "카지노 이용객", "명", 2),
        ("casino.yearly.visitor_share", "외래 방한객 대비 카지노 이용률", "%", 3),
        ("casino.yearly.visitor_growth", "카지노 이용객 전년 대비 증감률", "%", 4),
    )
    for key, label, unit, _ in visitor_defs:
        _series(connection, key, "카지노업 현황", label, unit, "yearly", "last", "문화체육관광부 카지노 통계")
    for row in casino_statistics.VISITOR_HISTORY:
        for key, _, _, index in visitor_defs:
            _point(connection, key, f"{row[0]}-01-01", row[index], f"visitor:{row[0]}")

    revenue_defs = (
        ("casino.yearly.tourism_fx_income", "관광 외화수입", "천USD", 1),
        ("casino.yearly.tourism_fx_growth", "관광 외화수입 증감률", "%", 2),
        ("casino.yearly.casino_fx_income", "카지노 외화수입", "천USD", 3),
        ("casino.yearly.casino_fx_growth", "카지노 외화수입 증감률", "%", 4),
        ("casino.yearly.fx_income_share", "관광 외화수입 대비 카지노 점유율", "%", 5),
    )
    for key, label, unit, _ in revenue_defs:
        _series(connection, key, "카지노업 현황", label, unit, "yearly", "last", "문화체육관광부 카지노 통계")
    for row in casino_statistics.REVENUE_HISTORY:
        for key, _, _, index in revenue_defs:
            _point(connection, key, f"{row[0]}-01-01", row[index], f"revenue:{row[0]}")

    for index, (label, values, _group) in enumerate(casino_statistics.FUND_ROWS, start=1):
        key = f"casino.fund.row_{index:02d}"
        _series(connection, key, "카지노업 현황", f"관광진흥개발기금 {label}", "백만원", "yearly", "last", "문화체육관광부 카지노 통계")
        for year, value in zip(casino_statistics.FUND_YEARS, values):
            _point(connection, key, f"{year}-01-01", value, f"fund:{index}:{year}")

    for index, casino in enumerate(casino_industry.CASINOS, start=1):
        slug = f"venue_{index:02d}"
        name = casino["venue_name"]
        for suffix, label, unit in (
            ("revenue", "매출액", "백만원"),
            ("visitors", "입장객", "명"),
            ("area", "허가 면적", "㎡"),
        ):
            key = f"casino.venue.{slug}.{suffix}"
            value = {
                "revenue": casino.get("revenue_2025"),
                "visitors": casino.get("visitors_2025"),
                "area": casino.get("area_sqm"),
            }[suffix]
            _series(connection, key, "카지노 사업장", f"{name} {label}", unit, "yearly", "last", "문화체육관광부 카지노 통계")
            _point(connection, key, "2025-01-01", value, f"venue:{index}:2025")


def synchronize_existing_data(connection, force=False):
    """기존 테이블을 파괴하지 않고 중앙 저장소에 멱등 이관한다."""
    state = queries.get_source_data_repository_state(connection, BACKFILL_STATE_KEY)
    if state and not force:
        _seed_static_statistics(connection)
        connection.commit()
        return False

    _seed_static_statistics(connection)

    tourism_slug = {"중국": "china", "일본": "japan", "대만": "taiwan", "몽골": "mongolia", "기타": "other"}
    tourism_totals = defaultdict(float)
    for row in connection.execute("SELECT * FROM tourism_visitor_stats").fetchall():
        slug = tourism_slug.get(row["nat_label"], str(row["nat_label"]))
        key = f"tourism.visitors.{slug}"
        _series(connection, key, "관광객", f"{row['nat_label']} 관광객", "명", "monthly", "sum", "한국문화관광연구원")
        _point(connection, key, row["ym"], row["visitor_count"], f"{row['ym']}:{row['nat_label']}")
        tourism_totals[row["ym"]] += float(row["visitor_count"] or 0)
    _series(connection, "tourism.visitors.total", "관광객", "전체 관광객", "명", "monthly", "sum", "한국문화관광연구원")
    for ym, value in tourism_totals.items():
        _point(connection, "tourism.visitors.total", ym, value, f"{ym}:total")

    quote_meta = {row["symbol"]: dict(row) for row in connection.execute("SELECT * FROM market_quotes").fetchall()}
    quote_fields = {
        "close_price": ("종가", "last"), "change_value": ("전일 대비", "last"),
        "change_rate": ("등락률", "last"), "open_price": ("시가", "last"),
        "high_price": ("고가", "last"), "low_price": ("저가", "last"),
        "volume": ("거래량", "sum"), "market_cap": ("시가총액", "last"),
    }
    for symbol, meta in quote_meta.items():
        for field, (metric_label, aggregation) in quote_fields.items():
            if meta.get(field) is None or not meta.get("base_date"):
                continue
            unit = "%" if field == "change_rate" else ("주" if field == "volume" else (meta.get("currency") or "KRW"))
            key = f"market.{symbol}.{field}"
            _series(connection, key, "주가", f"{meta.get('name') or symbol} {metric_label}", unit, "daily", aggregation, meta.get("source") or "공공데이터·글로벌 시세")
            _point(connection, key, meta["base_date"], meta[field], f"{symbol}:{meta['base_date']}")
    for row in connection.execute("SELECT * FROM market_quote_history").fetchall():
        meta = quote_meta.get(row["symbol"], {})
        key = f"market.{row['symbol']}.close_price"
        _series(connection, key, "주가", f"{meta.get('name') or row['symbol']} 종가", meta.get("currency") or "KRW", "daily", "last", meta.get("source") or "공공데이터·글로벌 시세")
        _point(connection, key, row["base_date"], row["close_price"], f"{row['symbol']}:{row['base_date']}")

    for row in connection.execute("SELECT * FROM economic_series").fetchall():
        key = f"economy.{row['series_code']}"
        _series(connection, key, "유가·환율", row["label"], row["unit"], "daily", "last", row["source"])
        _point(connection, key, row["observation_date"], row["value"], f"{row['series_code']}:{row['observation_date']}")

    for row in connection.execute("SELECT * FROM salary_snapshots").fetchall():
        key = f"salary.{row['entity_code']}.average"
        _series(connection, key, "연봉", f"{row['entity_name']} 평균 연봉", "만원", "monthly", "last", row["source_name"], url=row["source_url"])
        _point(connection, key, row["collected_date"], row["average_salary_manwon"], f"{row['entity_code']}:{row['collected_date']}")

    for row in connection.execute("SELECT * FROM performance_reports WHERE parsing_status='ok' AND parsed_json IS NOT NULL").fetchall():
        try:
            parsed = json.loads(row["parsed_json"])
        except (TypeError, ValueError):
            continue
        for field, label, unit in (
            ("group_sales_today", "그룹 매출", "백만원"),
            ("group_sales_yesterday", "그룹 전일 매출", "백만원"),
            ("casino_sales", "워커힐 카지노 매출", "백만원"),
            ("hotel_resort_sales", "호텔·리조트 매출", "백만원"),
            ("change_percent", "그룹 매출 증감률", "%"),
        ):
            value = queries._performance_number(parsed.get(field))
            if value is not None:
                key = f"performance.{field}"
                _series(connection, key, "경영실적", label, unit, "daily", "sum", "PARADIAN 경영실적 봇", internal=True)
                _point(connection, key, row["report_date"], value, str(row["telegram_message_id"]))

    active = connection.execute("SELECT COUNT(*) AS c FROM recruitment_jobs WHERE is_active=1").fetchone()["c"]
    latest_job = connection.execute("SELECT MAX(last_seen_at) AS latest FROM recruitment_jobs").fetchone()["latest"]
    if latest_job:
        _series(connection, "recruitment.active_jobs", "채용", "활성 채용공고", "건", "daily", "last", "채용 사이트 수집")
        _point(connection, "recruitment.active_jobs", latest_job, active, f"active:{_date(latest_job)}")

    queries.set_source_data_repository_state(connection, BACKFILL_STATE_KEY, now_kst().isoformat(timespec="seconds"))
    connection.commit()
    return True


def default_dates(grain):
    today = now_kst().date()
    if grain == "daily":
        start = today - timedelta(days=90)
    elif grain == "yearly":
        start = date(today.year - 10, 1, 1)
    else:
        start = date(today.year - 2, today.month, 1)
    return start.isoformat(), today.isoformat()


def _period_key(day, grain):
    if grain == "daily":
        return day
    if grain == "monthly":
        return day[:7]
    return day[:4]


def build_view(connection, *, grain="monthly", start_date=None, end_date=None, selected_keys=None, include_internal=False):
    grain = grain if grain in ALLOWED_GRAINS else "monthly"
    default_start, default_end = default_dates(grain)
    start_date = _date(start_date) if start_date else default_start
    end_date = _date(end_date) if end_date else default_end
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    if grain == "daily":
        earliest = (datetime.fromisoformat(end_date).date() - timedelta(days=366)).isoformat()
        start_date = max(start_date, earliest)

    series = queries.list_source_data_series(connection, include_internal=include_internal)
    series_map = {item["series_key"]: item for item in series}
    selected_keys = [key for key in (selected_keys or []) if key in series_map][:30]
    if not selected_keys:
        preferred = [
            "casino.yearly.casino_visitors", "casino.yearly.casino_fx_income",
            "tourism.visitors.china", "market.034230.close_price",
            "economy.FX_USD", "economy.OIL_B027",
        ]
        selected_keys = [key for key in preferred if key in series_map]
        if not selected_keys:
            selected_keys = list(series_map)[:6]

    points = queries.list_source_data_points(
        connection, selected_keys, start_date, end_date, include_internal=include_internal
    )
    grouped = defaultdict(lambda: defaultdict(list))
    raw_rows = []
    for point in points:
        period = _period_key(point["observation_date"], grain)
        grouped[point["series_key"]][period].append(point)
        meta = series_map[point["series_key"]]
        raw_rows.append({
            "date": point["observation_date"], "series_key": point["series_key"],
            "category": meta["category"], "label": meta["label"],
            "value": point["value"], "unit": meta["unit"], "source": meta["source_name"],
        })
    periods = sorted({period for values in grouped.values() for period in values})
    rows = []
    for key in selected_keys:
        meta = series_map[key]
        values = []
        for period in periods:
            bucket = grouped[key].get(period, [])
            if not bucket:
                values.append(None)
            elif meta["aggregation"] == "sum":
                values.append(sum(item["value"] for item in bucket))
            elif meta["aggregation"] == "avg":
                values.append(sum(item["value"] for item in bucket) / len(bucket))
            else:
                values.append(sorted(bucket, key=lambda item: item["observation_date"])[-1]["value"])
        rows.append({**meta, "values": values})
    categories = defaultdict(list)
    for item in series:
        categories[item["category"]].append(item)
    return {
        "grain": grain, "start_date": start_date, "end_date": end_date,
        "series": series, "categories": dict(categories), "selected_keys": selected_keys,
        "periods": periods, "rows": rows, "raw_rows": raw_rows,
        "stats": queries.source_data_repository_stats(connection, include_internal=include_internal),
    }

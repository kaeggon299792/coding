"""Company valuation multiples backed by the central source-data tables."""

COMPANIES = {
    "paradise": "파라다이스",
    "lotte_tour": "롯데관광개발",
    "gkl": "GKL",
    "kangwon_land": "강원랜드",
}
METRICS = (
    ("per", "PER"), ("pbr", "PBR"), ("psr", "PSR"),
    ("p_fcf", "P/FCF"), ("p_ocf", "P/OCF"),
    ("ev_ebitda", "EV/EBITDA"), ("ev_sales", "EV/Sales"),
    ("ev_ebit", "EV/EBIT"), ("ev_ebitda_capex", "EV/(EBITDA-CapEx)"),
    ("ev_nopat", "EV/NOPAT"), ("ev_ic", "EV/IC"),
    ("peg_1y", "PEG Ratio +1Y"), ("peg_2y", "PEG Ratio +2Y"),
    ("peg_3y", "PEG Ratio +3Y"),
)
FIELDS = (
    ("current", "현재"), ("median_5y", "5Y 중앙값"),
    ("average_5y", "5Y 평균"), ("industry_median", "산업 중앙값"),
    ("ntm", "NTM"), ("fy1", "FY+1"), ("fy2", "FY+2"),
)
PREFIX = "company_expert."


def _comparison(current, benchmark):
    if current is None or benchmark is None:
        return "-"
    difference = current - benchmark
    if abs(difference) < 0.000001:
        return "유사"
    return "낮음" if difference < 0 else "높음"


def build_dashboard(connection, selected_company=None):
    selected_company = selected_company if selected_company in COMPANIES else "paradise"
    rows = connection.execute(
        """
        SELECT s.series_key, p.value, p.observation_date, p.updated_at
        FROM source_data_series s
        JOIN source_data_points p ON p.series_key=s.series_key
        WHERE s.is_active=1 AND s.series_key LIKE ?
          AND p.observation_date=(
            SELECT MAX(p2.observation_date) FROM source_data_points p2
            WHERE p2.series_key=p.series_key
          )
        """,
        (f"{PREFIX}%",),
    ).fetchall()
    values = {}
    latest_date = None
    for row in rows:
        parts = row["series_key"].split(".")
        if len(parts) != 4:
            continue
        _, company, metric, field = parts
        values[(company, metric, field)] = row["value"]
        latest_date = max(latest_date or row["observation_date"], row["observation_date"])
    metrics = []
    for metric_code, label in METRICS:
        record = {
            field: values.get((selected_company, metric_code, field))
            for field, _ in FIELDS
        }
        comparison_values = [
            value for value in (
                record["current"], record["median_5y"], record["industry_median"]
            ) if value is not None and value >= 0
        ]
        scale = max(comparison_values or [1])
        record.update({
            "code": metric_code, "label": label,
            "vs_5y": _comparison(record["current"], record["median_5y"]),
            "vs_industry": _comparison(record["current"], record["industry_median"]),
            "current_width": round(max(0, record["current"] or 0) / scale * 100, 2),
            "median_5y_width": round(max(0, record["median_5y"] or 0) / scale * 100, 2),
            "industry_width": round(max(0, record["industry_median"] or 0) / scale * 100, 2),
        })
        metrics.append(record)
    metric_map = {item["code"]: item for item in metrics}
    available = [item for item in metrics if item["current"] is not None]
    groups = (
        ("market", "주가 기준 멀티플", "기업가치가 매출·순이익·현금흐름 대비 어느 수준인지 봅니다.", metrics[:5]),
        ("enterprise", "기업가치 기준 멀티플", "순차입금을 포함한 기업가치를 영업성과와 비교합니다.", metrics[5:11]),
        ("growth", "성장 조정 멀티플", "이익 성장률까지 반영해 현재 밸류에이션을 점검합니다.", metrics[11:]),
    )
    return {
        "companies": COMPANIES, "selected_company": selected_company,
        "selected_company_name": COMPANIES[selected_company],
        "metrics": metrics, "fields": FIELDS, "as_of": latest_date,
        "groups": groups,
        "available_count": len(available),
        "below_5y_count": sum(item["vs_5y"] == "낮음" for item in available),
        "below_industry_count": sum(item["vs_industry"] == "낮음" for item in available),
        "per": metric_map["per"],
        "pbr": metric_map["pbr"],
        "ev_ebitda": metric_map["ev_ebitda"],
    }

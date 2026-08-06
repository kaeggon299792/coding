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
METRIC_DESCRIPTIONS = {
    "per": "주가가 주당순이익의 몇 배인지 보여주는 대표적인 수익가치 지표입니다.",
    "pbr": "주가가 주당순자산의 몇 배인지 보여주는 자산가치 지표입니다.",
    "psr": "시가총액이 연간 매출의 몇 배인지 보여줍니다.",
    "p_fcf": "주가를 잉여현금흐름과 비교해 실제 남는 현금 대비 가격을 봅니다.",
    "p_ocf": "주가를 영업현금흐름과 비교해 본업의 현금창출력 대비 가격을 봅니다.",
    "ev_ebitda": "부채를 포함한 기업가치를 이자·세금·감가상각 전 이익과 비교합니다.",
    "ev_sales": "부채를 포함한 기업가치가 매출의 몇 배인지 보여줍니다.",
    "ev_ebit": "부채를 포함한 기업가치를 영업이익과 비교합니다.",
    "ev_ebitda_capex": "설비투자까지 뺀 현금창출력과 기업가치를 비교합니다.",
    "ev_nopat": "기업가치를 세후 영업이익과 비교합니다.",
    "ev_ic": "기업가치를 사업에 실제 투입된 자본과 비교합니다.",
    "peg_1y": "PER을 향후 1년 이익성장률로 나눠 성장성까지 함께 봅니다.",
    "peg_2y": "PER을 향후 2년 이익성장률로 나눠 성장성까지 함께 봅니다.",
    "peg_3y": "PER을 향후 3년 이익성장률로 나눠 성장성까지 함께 봅니다.",
}


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
        record.update({
            "code": metric_code, "label": label,
            "description": METRIC_DESCRIPTIONS.get(metric_code, "기업가치를 같은 기준으로 비교하는 지표입니다."),
            "vs_5y": _comparison(record["current"], record["median_5y"]),
            "vs_industry": _comparison(record["current"], record["industry_median"]),
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

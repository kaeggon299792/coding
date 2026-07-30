"""2024년 국내 외국인전용 카지노업 현황 데이터와 화면용 집계."""

from __future__ import annotations

from collections import Counter


CASINOS = (
    {
        "region": "서울", "venue_name": "파라다이스카지노 워커힐점", "company_name": "㈜파라다이스",
        "permit_date": "1968-03-05", "place": "워커힐호텔",
        "address": "서울특별시 광진구 워커힐로 177", "area_sqm": 3082.54,
        "operation": "임대", "grade": "특1", "revenue_2024": 328624, "visitors_2024": 437882,
    },
    {
        "region": "서울", "venue_name": "세븐럭카지노 서울강남코엑스점", "company_name": "그랜드코리아레저㈜",
        "permit_date": "2005-01-28", "place": "코엑스컨벤션별관",
        "address": "서울특별시 강남구 테헤란로87길 58", "area_sqm": 2158.32,
        "operation": "임대", "grade": "컨벤션", "revenue_2024": 180215, "visitors_2024": 345241,
    },
    {
        "region": "서울", "venue_name": "세븐럭카지노 서울드래곤시티점", "company_name": "그랜드코리아레저㈜",
        "permit_date": "2005-01-28", "place": "서울드래곤시티",
        "address": "서울특별시 중구 소월로 50", "area_sqm": 2137.20,
        "operation": "임대", "grade": "특1", "revenue_2024": 154483, "visitors_2024": 529767,
    },
    {
        "region": "부산", "venue_name": "세븐럭카지노 부산롯데점", "company_name": "그랜드코리아레저㈜",
        "permit_date": "2005-01-28", "place": "롯데호텔부산",
        "address": "부산광역시 부산진구 가야대로 772", "area_sqm": 1583.73,
        "operation": "임대", "grade": "특1", "revenue_2024": 58990, "visitors_2024": 170048,
    },
    {
        "region": "부산", "venue_name": "파라다이스카지노부산지점", "company_name": "㈜파라다이스",
        "permit_date": "1978-10-29", "place": "파라다이스호텔",
        "address": "부산광역시 해운대구 해운대해변로 296", "area_sqm": 1483.66,
        "operation": "임대", "grade": "특1", "revenue_2024": 62904, "visitors_2024": 83170,
    },
    {
        "region": "인천", "venue_name": "파라다이스카지노", "company_name": "㈜파라다이스세가사미",
        "permit_date": "1967-08-10", "place": "파라다이스시티",
        "address": "인천광역시 중구 영종해안남로321길 186", "area_sqm": 8726.80,
        "operation": "직영", "grade": "특1", "revenue_2024": 422686, "visitors_2024": 364564,
    },
    {
        "region": "인천", "venue_name": "인스파이어카지노", "company_name": "㈜인스파이어 인티그레이티드 리조트",
        "permit_date": "2024-01-23", "place": "인스파이어 리조트",
        "address": "인천광역시 중구 공항문화로 127", "area_sqm": 14372.00,
        "operation": "직영", "grade": "특1", "revenue_2024": 173318, "visitors_2024": 281243,
    },
    {
        "region": "강원·평창", "venue_name": "알펜시아카지노", "company_name": "㈜지바스",
        "permit_date": "1980-12-09", "place": "알펜시아리조트",
        "address": "강원도 평창군 대관령면 솔봉로 325", "area_sqm": 632.69,
        "operation": "임대", "grade": "특1", "revenue_2024": 0, "visitors_2024": 0,
    },
    {
        "region": "대구", "venue_name": "인터불고대구카지노", "company_name": "㈜골든크라운",
        "permit_date": "1979-04-11", "place": "인터불고호텔",
        "address": "대구광역시 수성구 팔현길 212", "area_sqm": 1485.24,
        "operation": "임대", "grade": "특1", "revenue_2024": 21286, "visitors_2024": 69566,
    },
    {
        "region": "제주", "venue_name": "공즈카지노", "company_name": "길상창휘(유)",
        "permit_date": "1975-10-15", "place": "라마다프라자 제주호텔",
        "address": "제주특별자치도 제주시 탑동로 66", "area_sqm": 1604.84,
        "operation": "임대", "grade": "특1", "revenue_2024": 7289, "visitors_2024": 27518,
    },
    {
        "region": "제주", "venue_name": "파라다이스카지노제주지점", "company_name": "㈜파라다이스",
        "permit_date": "1990-09-01", "place": "메종글래드제주",
        "address": "제주특별자치도 제주시 노연로 80", "area_sqm": 1195.92,
        "operation": "임대", "grade": "특1", "revenue_2024": 16491, "visitors_2024": 70977,
    },
    {
        "region": "제주", "venue_name": "세븐스타카지노", "company_name": "㈜청해",
        "permit_date": "1991-07-31", "place": "롯데호텔제주",
        "address": "제주특별자치도 서귀포시 중문관광로72번길 35", "area_sqm": 1175.85,
        "operation": "임대", "grade": "특1", "revenue_2024": 43587, "visitors_2024": 34132,
    },
    {
        "region": "제주", "venue_name": "제주오리엔탈카지노", "company_name": "㈜건하",
        "permit_date": "1990-11-06", "place": "오리엔탈호텔",
        "address": "제주특별자치도 제주시 탑동로 47", "area_sqm": 865.25,
        "operation": "임대", "grade": "특1", "revenue_2024": 794, "visitors_2024": 6681,
    },
    {
        "region": "제주", "venue_name": "드림타워카지노", "company_name": "㈜엘티엔터테인먼트",
        "permit_date": "1985-04-11", "place": "제주드림타워",
        "address": "제주특별자치도 제주시 노연로 12", "area_sqm": 5529.63,
        "operation": "임대", "grade": "특1", "revenue_2024": 320319, "visitors_2024": 383073,
    },
    {
        "region": "제주", "venue_name": "제주썬카지노", "company_name": "㈜지앤엘",
        "permit_date": "1990-09-01", "place": "제주썬호텔",
        "address": "제주특별자치도 제주시 삼무로 67", "area_sqm": 1509.12,
        "operation": "직영", "grade": "특1", "revenue_2024": 883, "visitors_2024": 13005,
    },
    {
        "region": "제주", "venue_name": "랜딩카지노", "company_name": "람정엔터테인먼트코리아㈜",
        "permit_date": "1990-09-01", "place": "제주신화월드",
        "address": "제주특별자치도 서귀포시 안덕면 신화역사로 304번길 38", "area_sqm": 5641.10,
        "operation": "임대", "grade": "특1", "revenue_2024": 69302, "visitors_2024": 126904,
    },
    {
        "region": "제주", "venue_name": "메가럭카지노", "company_name": "㈜메가럭",
        "permit_date": "1995-12-28", "place": "신라호텔제주",
        "address": "제주특별자치도 서귀포시 중문관광로72번길 75", "area_sqm": 1347.72,
        "operation": "임대", "grade": "특1", "revenue_2024": 249, "visitors_2024": 686,
    },
)

REGION_MAP = {
    "서울": {"x": 145, "y": 135},
    "인천": {"x": 108, "y": 151},
    "강원·평창": {"x": 268, "y": 155},
    "대구": {"x": 269, "y": 318},
    "부산": {"x": 315, "y": 390},
    "제주": {"x": 145, "y": 510},
}


def build_dashboard(selected_region: str = "") -> dict:
    regions = tuple(REGION_MAP)
    if selected_region not in regions:
        selected_region = ""

    items = [
        {**item, "revenue_share": item["revenue_2024"] / 422686 * 100}
        for item in CASINOS
        if not selected_region or item["region"] == selected_region
    ]
    operation_counts = Counter(item["operation"] for item in CASINOS)
    markers = []
    for region, position in REGION_MAP.items():
        region_items = [item for item in CASINOS if item["region"] == region]
        markers.append({
            "region": region,
            **position,
            "count": len(region_items),
            "revenue": sum(item["revenue_2024"] for item in region_items),
            "selected": region == selected_region,
        })

    return {
        "items": items,
        "regions": regions,
        "selected_region": selected_region,
        "markers": markers,
        "summary": {
            "venue_count": len(CASINOS),
            "area_sqm": round(sum(item["area_sqm"] for item in CASINOS), 2),
            "revenue_2024": sum(item["revenue_2024"] for item in CASINOS),
            "visitors_2024": sum(item["visitors_2024"] for item in CASINOS),
            "direct_count": operation_counts["직영"],
            "leased_count": operation_counts["임대"],
        },
    }

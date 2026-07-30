"""2025년 국내 외국인전용 카지노업 현황 데이터와 화면용 집계."""

from __future__ import annotations

from collections import Counter


CASINOS = (
    {
        "region": "서울", "venue_name": "파라다이스카지노 워커힐점", "company_name": "㈜파라다이스",
        "permit_date": "1968-03-05", "place": "워커힐호텔",
        "address": "서울특별시 광진구 워커힐로 177", "area_sqm": 3082.54,
        "operation": "임대", "grade": "5성", "revenue_2025": 342228, "visitors_2025": 476757,
    },
    {
        "region": "서울", "venue_name": "세븐럭카지노 서울강남코엑스점", "company_name": "그랜드코리아레저㈜",
        "permit_date": "2005-01-28", "place": "코엑스컨벤션별관",
        "address": "서울특별시 강남구 테헤란로87길 58", "area_sqm": 2158.32,
        "operation": "임대", "grade": "컨벤션", "revenue_2025": 205608, "visitors_2025": 362045,
    },
    {
        "region": "서울", "venue_name": "세븐럭카지노 서울드래곤시티점", "company_name": "그랜드코리아레저㈜",
        "permit_date": "2005-01-28", "place": "서울드래곤시티",
        "address": "서울특별시 중구 소월로 50", "area_sqm": 2137.20,
        "operation": "임대", "grade": "5성", "revenue_2025": 150667, "visitors_2025": 571622,
    },
    {
        "region": "부산", "venue_name": "세븐럭카지노 부산롯데점", "company_name": "그랜드코리아레저㈜",
        "permit_date": "2005-01-28", "place": "롯데호텔부산",
        "address": "부산광역시 부산진구 가야대로 772", "area_sqm": 1583.73,
        "operation": "임대", "grade": "5성", "revenue_2025": 69051, "visitors_2025": 183498,
    },
    {
        "region": "부산", "venue_name": "파라다이스카지노부산지점", "company_name": "㈜파라다이스",
        "permit_date": "1978-10-29", "place": "파라다이스호텔",
        "address": "부산광역시 해운대구 해운대해변로 296", "area_sqm": 1483.66,
        "operation": "임대", "grade": "5성", "revenue_2025": 58073, "visitors_2025": 100098,
    },
    {
        "region": "인천", "venue_name": "파라다이스카지노", "company_name": "㈜파라다이스세가사미",
        "permit_date": "1967-08-10", "place": "파라다이스시티",
        "address": "인천광역시 중구 영종해안남로321길 186", "area_sqm": 8726.80,
        "operation": "직영", "grade": "5성", "revenue_2025": 485411, "visitors_2025": 435020,
    },
    {
        "region": "인천", "venue_name": "인스파이어카지노", "company_name": "㈜인스파이어 인티그레이티드 리조트",
        "permit_date": "2024-01-23", "place": "인스파이어 리조트",
        "address": "인천광역시 중구 공항문화로 127", "area_sqm": 14649.71,
        "operation": "직영", "grade": "5성", "revenue_2025": 286009, "visitors_2025": 379161,
    },
    {
        "region": "강원·평창", "venue_name": "알펜시아카지노", "company_name": "㈜지바스",
        "permit_date": "1980-12-09", "place": "알펜시아리조트",
        "address": "강원도 평창군 대관령면 솔봉로 325", "area_sqm": 632.69,
        "operation": "임대", "grade": "5성", "revenue_2025": 0, "visitors_2025": 0,
    },
    {
        "region": "대구", "venue_name": "호텔인터불고대구카지노", "company_name": "㈜골든크라운",
        "permit_date": "1979-04-11", "place": "인터불고호텔",
        "address": "대구광역시 수성구 팔현길 212", "area_sqm": 1485.24,
        "operation": "임대", "grade": "5성", "revenue_2025": 20140, "visitors_2025": 71960,
    },
    {
        "region": "제주", "venue_name": "제주완리카지노", "company_name": "길상창휘(유)",
        "permit_date": "1975-10-15", "place": "라마다프라자 제주호텔",
        "address": "제주특별자치도 제주시 탑동로 66", "area_sqm": 1604.84,
        "operation": "임대", "grade": "5성", "revenue_2025": 0, "visitors_2025": 0,
    },
    {
        "region": "제주", "venue_name": "파라다이스카지노제주지점", "company_name": "㈜파라다이스",
        "permit_date": "1990-09-01", "place": "메종글래드제주",
        "address": "제주특별자치도 제주시 노연로 80", "area_sqm": 1195.92,
        "operation": "임대", "grade": "5성", "revenue_2025": 23898, "visitors_2025": 101071,
    },
    {
        "region": "제주", "venue_name": "세븐스타카지노", "company_name": "㈜청해",
        "permit_date": "1991-07-31", "place": "롯데호텔제주",
        "address": "제주특별자치도 서귀포시 중문관광로72번길 35", "area_sqm": 1175.85,
        "operation": "임대", "grade": "5성", "revenue_2025": 40949, "visitors_2025": 36722,
    },
    {
        "region": "제주", "venue_name": "제주오리엔탈카지노", "company_name": "㈜건하",
        "permit_date": "1990-11-06", "place": "오리엔탈호텔",
        "address": "제주특별자치도 제주시 탑동로 47", "area_sqm": 865.25,
        "operation": "임대", "grade": "5성", "revenue_2025": 656, "visitors_2025": 15473,
    },
    {
        "region": "제주", "venue_name": "드림타워카지노", "company_name": "㈜엘티엔터테인먼트",
        "permit_date": "1985-04-11", "place": "제주드림타워",
        "address": "제주특별자치도 제주시 노연로 12", "area_sqm": 5841.14,
        "operation": "임대", "grade": "5성", "revenue_2025": 520646, "visitors_2025": 590332,
    },
    {
        "region": "제주", "venue_name": "블루원카지노", "company_name": "헤븐㈜",
        "permit_date": "1990-09-01", "place": "제주 지역",
        "address": "상세 영업장 주소 확인 필요", "area_sqm": 1240.44,
        "operation": "임대", "grade": "5성", "revenue_2025": 379, "visitors_2025": 8304,
    },
    {
        "region": "제주", "venue_name": "레스에이카지노", "company_name": "람정엔터테인먼트코리아㈜",
        "permit_date": "1990-09-01", "place": "제주신화월드",
        "address": "제주특별자치도 서귀포시 안덕면 신화역사로 304번길 38", "area_sqm": 5646.10,
        "operation": "임대", "grade": "5성", "revenue_2025": 54186, "visitors_2025": 153977,
    },
    {
        "region": "제주", "venue_name": "골드마운틴카지노", "company_name": "㈜금산",
        "permit_date": "1995-12-28", "place": "제주 지역",
        "address": "상세 영업장 주소 확인 필요", "area_sqm": 1347.72,
        "operation": "임대", "grade": "5성", "revenue_2025": 5861, "visitors_2025": 8011,
    },
)

REGION_MAP = {
    "서울": {"x": 40, "y": 20},
    "인천": {"x": 35, "y": 22},
    "강원·평창": {"x": 64, "y": 22},
    "대구": {"x": 64, "y": 50},
    "부산": {"x": 70, "y": 59},
    "제주": {"x": 37, "y": 90},
}


def build_dashboard(selected_region: str = "") -> dict:
    regions = tuple(REGION_MAP)
    if selected_region not in regions:
        selected_region = ""

    items = [
        {**item, "revenue_share": item["revenue_2025"] / 520646 * 100}
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
            "revenue": sum(item["revenue_2025"] for item in region_items),
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
            "revenue_2025": sum(item["revenue_2025"] for item in CASINOS),
            "visitors_2025": sum(item["visitors_2025"] for item in CASINOS),
            "direct_count": operation_counts["직영"],
            "leased_count": operation_counts["임대"],
        },
    }

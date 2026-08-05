"""공개 채용정보 원문에서 평균연봉을 확인한다.

검색결과 페이지 자체를 수집하지 않고 검색에 노출되는 원 출처를 조회한다.
수집 실패 시 호출자가 기존 DB 값을 유지할 수 있도록 실패 항목을 분리한다.
"""

import html as html_module
import re
from datetime import datetime
from urllib.parse import unquote

import config
from services.http_utils import get_with_hard_timeout
from utils import now_kst


SOURCES = (
    {
        "entity_code": "paradise",
        "entity_name": "파라다이스",
        "url": "https://www.jobkorea.co.kr/company/1535297/Salary",
        "source_name": "잡코리아",
        "kind": "jobkorea",
    },
    {
        "entity_code": "gkl",
        "entity_name": "GKL",
        "url": "https://www.jobkorea.co.kr/company/1469899/Salary",
        "source_name": "잡코리아",
        "kind": "jobkorea",
    },
    {
        "entity_code": "kangwon_land",
        "entity_name": "강원랜드",
        "url": "https://www.jobkorea.co.kr/company/1683297/Salary",
        "source_name": "잡코리아",
        "kind": "jobkorea",
    },
    {
        "entity_code": "lotte_tour",
        "entity_name": "롯데관광개발",
        "url": "https://www.openbizdata.com/lottetourdev/",
        "source_name": "OpenBizData",
        "kind": "openbiz",
    },
)

# 국민연금공단의 공식 사업장 API를 이용하는 고용 지표입니다. 사업장별 고지액,
# 가입자 수, 취득·상실 인원으로 계산하므로 화면에서는 추정치임을 함께 안내합니다.
NPS_API_BASE = "https://apis.data.go.kr/B552015/NpsBplcInfoInqireServiceV2"
NPS_SOURCE_URL = "https://www.data.go.kr/data/3046071/openapi.do"
EMPLOYMENT_METRIC_SOURCES = (
    {
        "entity_code": "paradise", "entity_name": "파라다이스",
        "query_name": "파라다이스", "business_prefix": "203814",
        "address_keyword": "중구",
        "source_name": "국민연금 기준",
    },
    {
        "entity_code": "gkl", "entity_name": "GKL",
        "query_name": "그랜드코리아레저", "business_prefix": "104819",
        "address_keyword": "강남구",
        "source_name": "국민연금 기준",
    },
    {
        "entity_code": "kangwon_land", "entity_name": "강원랜드",
        "query_name": "강원랜드", "business_prefix": "225811",
        "address_keyword": "정선군",
        "source_name": "국민연금 기준",
    },
    {
        "entity_code": "lotte_tour", "entity_name": "롯데관광개발",
        "query_name": "롯데관광개발", "business_prefix": "101811",
        "address_keyword": "제주시",
        "source_name": "국민연금 기준",
    },
    {
        "entity_code": "paradise_segasammy", "entity_name": "㈜파라다이스세가사미",
        "query_name": "파라다이스세가사미", "address_keyword": "중구",
        "source_name": "국민연금 기준", "optional": True,
    },
    {
        "entity_code": "inspire", "entity_name": "㈜인스파이어 인티그레이티드 리조트",
        "query_name": "인스파이어인티그레이티드리조트",
        "business_prefix": "496860", "address_keyword": "중구",
        "source_name": "국민연금 기준", "optional": True,
    },
    {
        "entity_code": "gvas", "entity_name": "㈜지바스",
        "query_name": "지바스", "address_keyword": "평창군",
        "source_name": "국민연금 기준", "optional": True,
    },
    {
        "entity_code": "golden_crown", "entity_name": "㈜골든크라운",
        "query_name": "골든크라운", "address_keyword": "수성구",
        "source_name": "국민연금 기준", "optional": True,
    },
    {
        "entity_code": "gilsang_changhwi", "entity_name": "길상창휘(유)",
        "query_name": "길상창휘", "address_keyword": "제주시",
        "source_name": "국민연금 기준", "optional": True,
    },
    {
        "entity_code": "cheonghae", "entity_name": "㈜청해",
        "query_name": "청해", "address_keyword": "서귀포시",
        "source_name": "국민연금 기준", "optional": True,
    },
    {
        "entity_code": "geonha", "entity_name": "㈜건하",
        "query_name": "건하", "address_keyword": "제주시",
        "source_name": "국민연금 기준", "optional": True,
    },
    {
        "entity_code": "heaven", "entity_name": "헤븐㈜",
        "query_name": "헤븐", "address_keyword": "제주시",
        "source_name": "국민연금 기준", "optional": True,
    },
    {
        "entity_code": "landing_entertainment", "entity_name": "람정엔터테인먼트코리아㈜",
        "query_name": "람정엔터테인먼트코리아", "address_keyword": "서귀포시",
        "source_name": "국민연금 기준", "optional": True,
    },
    {
        "entity_code": "geumsan", "entity_name": "㈜금산",
        "query_name": "금산", "address_keyword": "제주시",
        "source_name": "국민연금 기준", "optional": True,
    },
)

REVIEW_SOURCES = (
    {
        "entity_code": "paradise",
        "entity_name": "파라다이스",
        "source_code": "jobplanet",
        "source_name": "잡플래닛",
        "url": (
            "https://www.jobplanet.co.kr/companies/50639/reviews/"
            "%ED%8C%8C%EB%9D%BC%EB%8B%A4%EC%9D%B4%EC%8A%A4"
        ),
        "kind": "jobplanet",
    },
    {
        "entity_code": "paradise",
        "entity_name": "파라다이스",
        "source_code": "blind",
        "source_name": "블라인드",
        "url": (
            "https://www.teamblind.com/kr/company/"
            "%ED%8C%8C%EB%9D%BC%EB%8B%A4%EC%9D%B4%EC%8A%A4/"
        ),
        "kind": "blind",
    },
    {
        "entity_code": "gkl",
        "entity_name": "GKL",
        "source_code": "jobplanet",
        "source_name": "잡플래닛 · GKL",
        "url": (
            "https://www.jobplanet.co.kr/companies/44165/reviews/"
            "%EA%B7%B8%EB%9E%9C%EB%93%9C%EC%BD%94%EB%A6%AC%EC%95%84%EB%A0%88%EC%A0%80"
        ),
        "kind": "jobplanet",
    },
    {
        "entity_code": "gkl",
        "entity_name": "GKL",
        "source_code": "jobplanet_sevenluck",
        "source_name": "잡플래닛 · 세븐럭카지노",
        "url": (
            "https://www.jobplanet.co.kr/companies/316912/reviews/"
            "%EC%84%B8%EB%B8%90%EB%9F%AD%EC%B9%B4%EC%A7%80%EB%85%B8"
        ),
        "kind": "jobplanet",
    },
    {
        "entity_code": "gkl",
        "entity_name": "GKL",
        "source_code": "blind",
        "source_name": "블라인드 · GKL",
        "url": "https://www.teamblind.com/kr/company/GKL/",
        "kind": "blind",
    },
    {
        "entity_code": "kangwon_land",
        "entity_name": "강원랜드",
        "source_code": "jobplanet",
        "source_name": "잡플래닛 · 강원랜드",
        "url": (
            "https://www.jobplanet.co.kr/companies/85983/reviews/"
            "%EA%B0%95%EC%9B%90%EB%9E%9C%EB%93%9C"
        ),
        "kind": "jobplanet",
    },
    {
        "entity_code": "kangwon_land",
        "entity_name": "강원랜드",
        "source_code": "blind",
        "source_name": "블라인드 · 강원랜드",
        "url": (
            "https://www.teamblind.com/kr/company/"
            "%EA%B0%95%EC%9B%90%EB%9E%9C%EB%93%9C/"
        ),
        "kind": "blind",
    },
    {
        "entity_code": "lotte_tour",
        "entity_name": "롯데관광개발",
        "source_code": "jobplanet",
        "source_name": "잡플래닛 · 롯데관광개발",
        "url": (
            "https://www.jobplanet.co.kr/companies/35673/reviews/"
            "%EB%A1%AF%EB%8D%B0%EA%B4%80%EA%B4%91%EA%B0%9C%EB%B0%9C"
        ),
        "kind": "jobplanet",
    },
    {
        "entity_code": "lotte_tour",
        "entity_name": "롯데관광개발",
        "source_code": "blind",
        "source_name": "블라인드 · 롯데관광개발",
        "url": (
            "https://www.teamblind.com/kr/company/"
            "%EB%A1%AF%EB%8D%B0%EA%B4%80%EA%B4%91%EA%B0%9C%EB%B0%9C/"
        ),
        "kind": "blind",
    },
    {
        "entity_code": "lotte_tour",
        "entity_name": "롯데관광개발",
        "source_code": "jobplanet_dreamtower",
        "source_name": "잡플래닛 · 제주드림타워",
        "url": (
            "https://www.jobplanet.co.kr/companies/356954/reviews/"
            "%EC%A0%9C%EC%A3%BC%EB%93%9C%EB%A6%BC%ED%83%80%EC%9B%8C"
        ),
        "kind": "jobplanet",
    },
    {
        "entity_code": "lotte_tour",
        "entity_name": "롯데관광개발",
        "source_code": "blind_dreamtower",
        "source_name": "블라인드 · 제주드림타워",
        "url": (
            "https://www.teamblind.com/kr/company/"
            "%EC%A0%9C%EC%A3%BC%EB%93%9C%EB%A6%BC%ED%83%80%EC%9B%8C/"
        ),
        "kind": "blind",
    },
    {
        "entity_code": "paradise_segasammy",
        "entity_name": "파라다이스세가사미",
        "source_code": "jobplanet",
        "source_name": "잡플래닛 · 파라다이스세가사미",
        "url": (
            "https://www.jobplanet.co.kr/companies/148195/reviews/"
            "%ED%8C%8C%EB%9D%BC%EB%8B%A4%EC%9D%B4%EC%8A%A4%EC%84%B8%EA%B0%80%EC%82%AC%EB%AF%B8"
        ),
        "kind": "jobplanet",
    },
    {
        "entity_code": "paradise_segasammy",
        "entity_name": "파라다이스세가사미",
        "source_code": "blind",
        "source_name": "블라인드 · 파라다이스세가사미",
        "url": (
            "https://www.teamblind.com/kr/company/"
            "%ED%8C%8C%EB%9D%BC%EB%8B%A4%EC%9D%B4%EC%8A%A4%EC%84%B8%EA%B0%80%EC%82%AC%EB%AF%B8/"
        ),
        "kind": "blind",
    },
    {
        "entity_code": "inspire",
        "entity_name": "인스파이어 인티그레이티드 리조트",
        "source_code": "jobplanet",
        "source_name": "잡플래닛 · 인스파이어",
        "url": (
            "https://www.jobplanet.co.kr/companies/393355/reviews/"
            "%EC%9D%B8%EC%8A%A4%ED%8C%8C%EC%9D%B4%EC%96%B4%EC%9D%B8%ED%8B%B0%EA%B7%B8%EB%A0%88%EC%9D%B4%ED%8B%B0%EB%93%9C%EB%A6%AC%EC%A1%B0%ED%8A%B8"
        ),
        "kind": "jobplanet",
    },
    {
        "entity_code": "inspire",
        "entity_name": "인스파이어 인티그레이티드 리조트",
        "source_code": "blind",
        "source_name": "블라인드 · 인스파이어",
        "url": (
            "https://www.teamblind.com/kr/company/"
            "%EC%9D%B8%EC%8A%A4%ED%8C%8C%EC%9D%B4%EC%96%B4%EC%9D%B8%ED%8B%B0%EA%B7%B8%EB%A0%88%EC%9D%B4%ED%8B%B0%EB%93%9C%EB%A6%AC%EC%A1%B0%ED%8A%B8/"
        ),
        "kind": "blind",
    },
    {
        "entity_code": "gvas",
        "entity_name": "㈜지바스",
        "source_code": "jobplanet",
        "source_name": "잡플래닛 · 지바스",
        "url": (
            "https://www.jobplanet.co.kr/companies/374661/reviews/"
            "%EC%A7%80%EB%B0%94%EC%8A%A4"
        ),
        "kind": "jobplanet",
    },
    {
        "entity_code": "golden_crown",
        "entity_name": "㈜골든크라운",
        "source_code": "jobplanet",
        "source_name": "잡플래닛 · 골든크라운",
        "url": (
            "https://www.jobplanet.co.kr/companies/149947/reviews/"
            "%EA%B3%A8%EB%93%A0%ED%81%AC%EB%9D%BC%EC%9A%B4"
        ),
        "kind": "jobplanet",
    },
    {
        "entity_code": "golden_crown",
        "entity_name": "㈜골든크라운",
        "source_code": "jobplanet_interburgo",
        "source_name": "잡플래닛 · 호텔인터불고엑스코(영업장 참고)",
        "url": (
            "https://www.jobplanet.co.kr/companies/141004/reviews/"
            "%ED%98%B8%ED%85%94%EC%9D%B8%ED%84%B0%EB%B6%88%EA%B3%A0%EC%97%91%EC%8A%A4%EC%BD%94"
        ),
        "kind": "jobplanet",
    },
    {
        "entity_code": "golden_crown",
        "entity_name": "㈜골든크라운",
        "source_code": "blind_interburgo",
        "source_name": "블라인드 · 인터불고엑스코(영업장 참고)",
        "url": (
            "https://www.teamblind.com/kr/company/"
            "%EC%9D%B8%ED%84%B0%EB%B6%88%EA%B3%A0%EC%97%91%EC%8A%A4%EC%BD%94/reviews"
        ),
        "kind": "blind",
    },
    {
        "entity_code": "gilsang_changhwi",
        "entity_name": "길상창휘(유)",
        "source_code": "jobplanet",
        "source_name": "잡플래닛 · 길상창휘",
        "url": (
            "https://www.jobplanet.co.kr/companies/325987/reviews/"
            "%EA%B8%B8%EC%83%81%EC%B0%BD%ED%9C%98"
        ),
        "kind": "jobplanet",
    },
    {
        "entity_code": "cheonghae",
        "entity_name": "㈜청해",
        "source_code": "jobplanet",
        "source_name": "잡플래닛 · 청해",
        "url": (
            "https://www.jobplanet.co.kr/companies/452082/reviews/"
            "%EC%B2%AD%ED%95%B4"
        ),
        "kind": "jobplanet",
    },
    {
        "entity_code": "geonha",
        "entity_name": "㈜건하",
        "source_code": "jobplanet",
        "source_name": "잡플래닛 · 건하",
        "url": (
            "https://www.jobplanet.co.kr/companies/443347/reviews/"
            "%EA%B1%B4%ED%95%98"
        ),
        "kind": "jobplanet",
    },
    {
        "entity_code": "landing_entertainment",
        "entity_name": "람정엔터테인먼트코리아㈜",
        "source_code": "jobplanet",
        "source_name": "잡플래닛 · 람정엔터테인먼트코리아",
        "url": (
            "https://www.jobplanet.co.kr/companies/337538/reviews/"
            "%EB%9E%8C%EC%A0%95%EC%97%94%ED%84%B0%ED%85%8C%EC%9D%B8%EB%A8%BC%ED%8A%B8%EC%BD%94%EB%A6%AC%EC%95%84"
        ),
        "kind": "jobplanet",
    },
    {
        "entity_code": "paradise",
        "entity_name": "파라다이스",
        "source_code": "jobplanet_glad",
        "source_name": "잡플래닛 · 글래드호텔앤리조트(참고)",
        "url": (
            "https://www.jobplanet.co.kr/companies/361539/reviews/"
            "%EA%B8%80%EB%9E%98%EB%93%9C%ED%98%B8%ED%85%94%EC%95%A4%EB%A6%AC%EC%A1%B0%ED%8A%B8"
        ),
        "kind": "jobplanet",
    },
    {
        "entity_code": "paradise",
        "entity_name": "파라다이스",
        "source_code": "blind_glad",
        "source_name": "블라인드 · 글래드호텔앤리조트(참고)",
        "url": (
            "https://www.teamblind.com/kr/company/"
            "%EA%B8%80%EB%9E%98%EB%93%9C%ED%98%B8%ED%85%94%EC%95%A4%EB%A6%AC%EC%A1%B0%ED%8A%B8/"
        ),
        "kind": "blind",
    },
)


def merge_operator_cards(items, operators):
    """DB 최신값에 카지노 운영 법인 전체를 합치고 미공개 법인도 보존한다."""
    companies = {
        item["entity_code"]: dict(item)
        for item in items
        if item.get("entity_type") != "industry"
    }
    benchmarks = [dict(item) for item in items if item.get("entity_type") == "industry"]
    merged = []
    registry_codes = set()
    for operator in operators:
        entity_code = operator["entity_code"]
        registry_codes.add(entity_code)
        item = companies.get(entity_code, {
            "entity_code": entity_code,
            "entity_name": operator["entity_name"],
            "entity_type": "company",
            "average_salary_manwon": None,
            "source_name": None,
            "source_url": None,
            "source_period": None,
            "collected_date": None,
            "review_ratings": [],
            "trend_points": "",
            "trend_area_points": "",
            "monthly_change": None,
            "salary_growth_rate": None,
            "turnover_rate": None,
        })
        item.update({
            "operator_name": operator["operator_name"],
            "venue_names": operator["venue_names"],
            "venue_count": operator["venue_count"],
            "regions": operator["regions"],
            "data_available": (
                item.get("average_salary_manwon") is not None
                or bool(item.get("review_ratings"))
            ),
        })
        merged.append(item)
    for entity_code, item in companies.items():
        if entity_code not in registry_codes:
            item.setdefault("data_available", True)
            merged.append(item)
    priority = {
        "paradise": 0,
        "gkl": 1,
        "kangwon_land": 2,
        "lotte_tour": 3,
    }
    merged.sort(key=lambda item: priority.get(item["entity_code"], 100))
    return [*merged, *benchmarks]


def _number(value):
    return int(str(value).replace(",", ""))


def _parse_jobkorea(html):
    title = re.search(
        r'<meta\s+name="title"\s+content="[^"]*?([0-9][0-9,]{3,})\s*만원',
        html,
        re.IGNORECASE,
    )
    if not title:
        raise ValueError("평균연봉 메타정보를 찾지 못했습니다.")
    period = re.search(r"(\d{4})년\s*기준", html)
    return _number(title.group(1)), period.group(1) if period else None


def _parse_openbiz(html):
    match = re.search(r"추정\s*평균\s*연봉[^0-9]{0,30}([0-9][0-9,]{3,})만원", html)
    if not match:
        raise ValueError("추정 평균연봉 정보를 찾지 못했습니다.")
    period = re.search(r"(\d{4})년\s*(\d{1,2})월\s*기준", html)
    label = f"{period.group(1)}.{int(period.group(2)):02d}" if period else None
    return _number(match.group(1)), label


def _plain_text(document):
    without_scripts = re.sub(
        r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>",
        " ",
        document,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return re.sub(
        r"\s+", " ", html_module.unescape(re.sub(r"<[^>]+>", " ", without_scripts))
    ).strip()


def _nps_items(payload):
    if not isinstance(payload, dict):
        raise ValueError("국민연금 API 응답 형식이 올바르지 않습니다.")
    if "OpenAPI_ServiceResponse" in payload:
        header = payload["OpenAPI_ServiceResponse"].get("cmmMsgHeader") or {}
        raise ValueError(header.get("returnAuthMsg") or header.get("errMsg") or "API 인증 오류")
    response = payload.get("response") or {}
    header = response.get("header") or {}
    if str(header.get("resultCode", "")) not in {"00", "0"}:
        raise ValueError(header.get("resultMsg") or "국민연금 API 조회 오류")
    items = ((response.get("body") or {}).get("items") or {}).get("item") or []
    return items if isinstance(items, list) else [items]


def _nps_request(operation, **params):
    if not config.NPS_API_KEY:
        raise ValueError("NPS_API_KEY가 설정되지 않았습니다.")
    response = get_with_hard_timeout(
        f"{NPS_API_BASE}/{operation}",
        hard_timeout_seconds=config.NPS_REQUEST_TIMEOUT_SECONDS,
        retry_attempts=2,
        timeout=(5, config.NPS_REQUEST_TIMEOUT_SECONDS),
        params={
            **params,
            "serviceKey": unquote(config.NPS_API_KEY.strip()),
            "dataType": "json",
            "pageNo": 1,
        },
        headers={"Accept": "application/json", "User-Agent": "CASINO-IN/1.0"},
    )
    response.raise_for_status()
    return _nps_items(response.json())


def _normalized_workplace_name(value):
    text = str(value or "")
    for token in ("주식회사", "유한회사", "(주)", "㈜"):
        text = text.replace(token, "")
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text).lower()


def _select_nps_history(rows, source):
    target = _normalized_workplace_name(source["query_name"])
    candidates = [
        row for row in rows
        if target in _normalized_workplace_name(row.get("wkplNm"))
        or _normalized_workplace_name(row.get("wkplNm")) in target
    ]
    business_prefix = source.get("business_prefix")
    business_matches = [
        row for row in candidates
        if business_prefix
        and str(row.get("bzowrRgstNo") or "").replace("*", "").startswith(business_prefix)
    ]
    if business_matches:
        candidates = business_matches
    address_keyword = source.get("address_keyword")
    address_matches = [
        row for row in candidates
        if address_keyword and address_keyword in str(row.get("wkplRoadNmDtlAddr") or "")
    ]
    if address_matches:
        candidates = address_matches
    if not candidates:
        raise ValueError(f"{source['entity_name']} 국민연금 사업장을 찾지 못했습니다.")
    groups = {}
    for row in candidates:
        group_key = (
            row.get("bzowrRgstNo") or "",
            _normalized_workplace_name(row.get("wkplNm")),
            row.get("wkplRoadNmDtlAddr") or "",
        )
        month = str(row.get("dataCrtYm") or "")
        if len(month) == 6 and month.isdigit() and row.get("seq") is not None:
            groups.setdefault(group_key, {})[month] = row
    if not groups:
        raise ValueError(f"{source['entity_name']} 월별 사업장 이력이 없습니다.")
    history = max(
        groups.values(),
        key=lambda values: (max(values, default=""), len(values)),
    )
    return [history[month] for month in sorted(history, reverse=True)[:13]][::-1]


def _estimated_annual_salary(detail):
    subscribers = float(detail.get("jnngpCnt") or 0)
    notice_amount = float(detail.get("crrmmNtcAmt") or 0)
    if subscribers <= 0 or notice_amount <= 0:
        return None
    return notice_amount / subscribers / 0.09 * 12


def _month_distance(start, end):
    start_year, start_month = int(start[:4]), int(start[4:6])
    end_year, end_month = int(end[:4]), int(end[4:6])
    return (end_year - start_year) * 12 + end_month - start_month


def _parse_blind_rating(document):
    structured = re.search(
        r'"@type"\s*:\s*"EmployerAggregateRating".*?'
        r'"ratingValue"\s*:\s*"?([0-5](?:\.\d+)?)"?.*?'
        r'"ratingCount"\s*:\s*"?([0-9,]+)"?',
        document,
        re.IGNORECASE | re.DOTALL,
    )
    if structured:
        return float(structured.group(1)), _number(structured.group(2))
    text = _plain_text(document)
    match = re.search(
        r"Rating\s+Score\s*([0-5](?:\.\d+)?)\s*\(([0-9,]+)개\s*리뷰\)",
        text,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError("블라인드 공개 평점 정보를 찾지 못했습니다.")
    return float(match.group(1)), _number(match.group(2))


def _parse_jobplanet_rating(document):
    text = _plain_text(document)
    patterns = (
        r"기업리뷰\s*([0-9,]+)건,?\s*([0-5](?:\.\d+)?)\s*리뷰평점",
        r"전체\s*리뷰\s*통계\s*\(([0-9,]+)명\)\s*([0-5](?:\.\d+)?)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return float(match.group(2)), _number(match.group(1))
    raise ValueError("잡플래닛 공개 평점 정보를 찾지 못했습니다.")


def fetch_source(source):
    response = get_with_hard_timeout(
        source["url"],
        hard_timeout_seconds=config.SALARY_REQUEST_TIMEOUT_SECONDS,
        retry_attempts=2,
        timeout=(5, config.SALARY_REQUEST_TIMEOUT_SECONDS),
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/126 Safari/537.36"
            )
        },
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    parser = _parse_jobkorea if source["kind"] == "jobkorea" else _parse_openbiz
    salary, source_period = parser(response.text)
    timestamp = now_kst()
    return {
        **source,
        "entity_type": "company",
        "average_salary_manwon": salary,
        "source_url": source["url"],
        "source_period": source_period,
        "collected_date": timestamp.date().isoformat(),
        "fetched_at": timestamp.isoformat(),
    }


def fetch_review_source(source):
    parser = _parse_blind_rating if source["kind"] == "blind" else _parse_jobplanet_rating
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/126 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
    }
    retrieval_method = "direct"
    try:
        response = get_with_hard_timeout(
            source["url"],
            hard_timeout_seconds=config.SALARY_REQUEST_TIMEOUT_SECONDS,
            retry_attempts=2,
            timeout=(5, config.SALARY_REQUEST_TIMEOUT_SECONDS),
            headers=headers,
        )
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding
        rating, review_count = parser(response.text)
    except Exception:  # 공개 원문이 봇 요청을 막거나 동적 렌더링만 제공하는 경우
        retrieval_method = "reader"
        reader_url = f"https://r.jina.ai/{source['url']}"
        response = get_with_hard_timeout(
            reader_url,
            hard_timeout_seconds=max(config.SALARY_REQUEST_TIMEOUT_SECONDS, 45),
            retry_attempts=2,
            timeout=(5, max(config.SALARY_REQUEST_TIMEOUT_SECONDS, 45)),
            headers={"Accept": "text/plain", "User-Agent": headers["User-Agent"]},
        )
        response.raise_for_status()
        rating, review_count = parser(response.text)
    timestamp = now_kst()
    return {
        **source,
        "rating": rating,
        "review_count": review_count,
        "source_url": source["url"],
        "retrieval_method": retrieval_method,
        "collected_date": timestamp.date().isoformat(),
        "fetched_at": timestamp.isoformat(),
    }


def fetch_employment_metrics(source):
    search_params = {"wkplNm": source["query_name"], "numOfRows": 100}
    if source.get("business_prefix"):
        search_params["bzowrRgstNo"] = source["business_prefix"]
    base_rows = _nps_request("getBassInfoSearchV2", **search_params)
    history = _select_nps_history(base_rows, source)
    monthly = []
    for row in history:
        detail_items = _nps_request(
            "getDetailInfoSearchV2", seq=row["seq"], numOfRows=10,
        )
        if not detail_items:
            continue
        period_items = _nps_request(
            "getPdAcctoSttusInfoSearchV2",
            seq=row["seq"],
            dataCrtYm=row["dataCrtYm"],
            numOfRows=10,
        )
        monthly.append({
            "month": str(row["dataCrtYm"]),
            "subscribers": float(detail_items[0].get("jnngpCnt") or 0),
            "annual_salary": _estimated_annual_salary(detail_items[0]),
            "leavers": float(
                (period_items[0] if period_items else {}).get("lssJnngpCnt") or 0
            ),
        })
    if not monthly:
        raise ValueError(f"{source['entity_name']} 국민연금 상세 이력이 없습니다.")
    salary_points = [item for item in monthly if item["annual_salary"]]
    salary_growth_rate = None
    growth_period_months = None
    if len(salary_points) >= 2:
        first, latest = salary_points[0], salary_points[-1]
        growth_period_months = _month_distance(first["month"], latest["month"])
        if growth_period_months > 0 and first["annual_salary"] > 0:
            raw_growth = latest["annual_salary"] / first["annual_salary"]
            salary_growth_rate = round(
                (raw_growth ** (12 / growth_period_months) - 1) * 100, 1
            )
    recent = monthly[-12:]
    headcounts = [item["subscribers"] for item in recent if item["subscribers"] > 0]
    turnover_rate = None
    if headcounts:
        average_headcount = sum(headcounts) / len(headcounts)
        turnover_rate = round(sum(item["leavers"] for item in recent) / average_headcount * 100, 1)
    timestamp = now_kst()
    return {
        **source,
        "estimated_average_salary_manwon": (
            round(salary_points[-1]["annual_salary"] / 10_000)
            if salary_points else None
        ),
        "salary_growth_rate": salary_growth_rate,
        "turnover_rate": turnover_rate,
        "growth_period_months": growth_period_months,
        "source_url": NPS_SOURCE_URL,
        "source_period": monthly[-1]["month"],
        "collected_date": timestamp.date().isoformat(),
        "fetched_at": timestamp.isoformat(),
    }


def build_benchmarks(companies):
    if not companies:
        return []
    timestamp = now_kst()
    common = {
        "collected_date": timestamp.date().isoformat(),
        "fetched_at": timestamp.isoformat(),
    }
    casino_average = round(
        sum(item["average_salary_manwon"] for item in companies) / len(companies)
    )
    # 호텔 비교군은 잡코리아의 호텔·여행·항공 순위에 함께 노출되는 대표 호텔
    # 6개사(호텔롯데, 호텔신라, 파르나스, 칼호텔, 호반호텔, 파라다이스호텔부산)
    # 최신 공개값의 단순평균이다. 개별 회사를 재배포하지 않고 비교 기준만 저장한다.
    hotel_reference_values = (6531, 6105, 5250, 6209, 4740, 5523)
    return [
        {
            **common,
            "entity_code": "casino_average",
            "entity_name": "카지노 4사 평균",
            "entity_type": "industry",
            "average_salary_manwon": casino_average,
            "source_name": "4사 공개값 단순평균",
            "source_url": None,
            "source_period": max(
                (item.get("source_period") or "" for item in companies), default=""
            ),
        },
        {
            **common,
            "entity_code": "hotel_average",
            "entity_name": "호텔업계 비교군 평균",
            "entity_type": "industry",
            "average_salary_manwon": round(
                sum(hotel_reference_values) / len(hotel_reference_values)
            ),
            "source_name": "잡코리아 호텔·여행·항공 비교군",
            "source_url": SOURCES[0]["url"],
            "source_period": f"{datetime.now().year}.07",
        },
    ]


def fetch_all():
    items, reviews, employment_metrics, errors, missing = [], [], [], [], []
    for source in SOURCES:
        try:
            items.append(fetch_source(source))
        except Exception as error:  # noqa: BLE001 - 다른 출처 수집은 계속한다.
            errors.append({"entity_code": source["entity_code"], "error": str(error)})
    for source in REVIEW_SOURCES:
        try:
            reviews.append(fetch_review_source(source))
        except Exception as error:  # noqa: BLE001 - 기존 정상 평점은 유지한다.
            errors.append({
                "entity_code": f"{source['entity_code']}.{source['source_code']}",
                "error": str(error),
            })
    for source in EMPLOYMENT_METRIC_SOURCES:
        try:
            employment_metrics.append(fetch_employment_metrics(source))
        except Exception as error:  # noqa: BLE001 - 기존 정상 지표는 유지한다.
            target = missing if source.get("optional") else errors
            target.append({
                "entity_code": f"{source['entity_code']}.employment",
                "error": str(error),
            })
    benchmark_items = build_benchmarks(items)
    existing_salary_codes = {item["entity_code"] for item in items}
    for employment in employment_metrics:
        estimated_salary = employment.get("estimated_average_salary_manwon")
        if employment["entity_code"] in existing_salary_codes or estimated_salary is None:
            continue
        items.append({
            "entity_code": employment["entity_code"],
            "entity_name": employment["entity_name"],
            "entity_type": "company",
            "average_salary_manwon": estimated_salary,
            "source_name": "국민연금 기준(추정)",
            "source_url": employment["source_url"],
            "source_period": employment["source_period"],
            "collected_date": employment["collected_date"],
            "fetched_at": employment["fetched_at"],
        })
    return {
        "items": [*items, *benchmark_items],
        "reviews": reviews,
        "employment_metrics": employment_metrics,
        "errors": errors,
        "missing": missing,
    }

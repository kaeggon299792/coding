"""공개 채용정보 원문에서 평균연봉을 확인한다.

검색결과 페이지 자체를 수집하지 않고 검색에 노출되는 원 출처를 조회한다.
수집 실패 시 호출자가 기존 DB 값을 유지할 수 있도록 실패 항목을 분리한다.
"""

import re
from datetime import datetime

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
    items, errors = [], []
    for source in SOURCES:
        try:
            items.append(fetch_source(source))
        except Exception as error:  # noqa: BLE001 - 다른 출처 수집은 계속한다.
            errors.append({"entity_code": source["entity_code"], "error": str(error)})
    return {"items": [*items, *build_benchmarks(items)], "errors": errors}

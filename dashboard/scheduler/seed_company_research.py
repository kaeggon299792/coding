"""공식 DART 자료와 검증된 회사 자료로 기업 기초 조사 프로필을 갱신한다."""

import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from dashboard_db import queries
from extensions import dashboard_db
from utils import now_kst


CURATED = {
    "파라다이스": {
        "business_summary": (
            "서울·인천·부산·제주에서 외국인 전용 카지노를 운영하고, 인천 영종도의 "
            "파라다이스시티 복합리조트와 호텔 사업을 영위한다."
        ),
        "strategy_summary": (
            "복합리조트 경쟁력과 외국인 VIP·매스 고객 회복을 기반으로 성장하면서 "
            "호텔·호스피탈리티 비중 확대를 통한 포트폴리오 다각화를 추진하는 흐름이다."
        ),
        "key_assets": ["파라다이스시티(인천 영종도)", "워커힐 카지노", "파라다이스 호텔 부산", "제주 카지노"],
        "opportunities": ["외국인 관광객 회복", "인천공항 접근성", "복합리조트 비카지노 매출 확대", "일본·중국 VIP 수요"],
        "risks": ["외국인 입국 수요 변동", "카지노 규제·세율", "대규모 시설 고정비", "인스파이어 등 영종도 경쟁 심화"],
        "extra_sources": [
            {"label": "파라다이스 공식 IR", "url": "https://paradisegroup.co.kr/ko/invest/ir/reference"},
        ],
    },
    "GKL": {
        "business_summary": (
            "한국관광공사 계열의 외국인 전용 카지노 운영사로, 세븐럭 브랜드를 통해 "
            "서울과 부산의 외국인 관광객을 대상으로 카지노 사업을 영위한다."
        ),
        "strategy_summary": (
            "공기업형 카지노 운영의 안정성과 관광 공공성을 바탕으로 고객 다변화, "
            "디지털 마케팅, 책임도박·ESG 체계 강화를 병행하는 구조다."
        ),
        "key_assets": ["세븐럭 강남 코엑스점", "세븐럭 서울드래곤시티점", "세븐럭 부산롯데점"],
        "opportunities": ["도심 접근성", "외래관광객 회복", "MICE 관광 연계", "공공 관광 네트워크"],
        "risks": ["외국인 전용 시장 의존", "공기업 규정과 의사결정 속도", "서울·부산 경쟁", "중국·일본 수요 변동"],
        "extra_sources": [
            {"label": "GKL 공식 홈페이지", "url": "https://www.grandkorea.com/"},
        ],
    },
    "강원랜드": {
        "business_summary": (
            "국내에서 내국인 출입이 가능한 카지노와 하이원 리조트의 호텔·콘도·스키·골프 "
            "등을 운영하며 폐광지역 경제 활성화라는 공공적 역할을 함께 수행한다."
        ),
        "strategy_summary": (
            "카지노 중심 구조에서 사계절 글로벌 복합리조트로 전환하고 시설 경쟁력을 높이는 "
            "K-HIT 프로젝트와 비카지노 콘텐츠 확대가 핵심 관찰 포인트다."
        ),
        "key_assets": ["강원랜드 카지노", "하이원 그랜드호텔", "하이원 스키리조트", "하이원CC·콘도"],
        "opportunities": ["내국인 카지노 독점성", "카지노 영업장 확장", "사계절 리조트 전환", "폐광지역 개발 정책 지원"],
        "risks": ["매출총량·베팅한도 등 규제", "지리적 접근성", "공공성과 수익성의 균형", "비카지노 투자 회수"],
        "extra_sources": [
            {"label": "강원랜드 공식 홈페이지", "url": "https://kangwonland.high1.com/"},
        ],
    },
    "롯데관광개발": {
        "business_summary": (
            "여행·크루즈 사업과 제주 드림타워 복합리조트를 운영하며, 드림타워 내 그랜드 하얏트 "
            "제주·외국인 전용 카지노·식음·리테일을 결합한 제주 관광 플랫폼을 보유한다."
        ),
        "strategy_summary": (
            "제주 드림타워의 카지노·호텔 가동률과 국제선 회복을 활용해 현금창출력을 높이고, "
            "고정비와 차입 부담을 관리하는 것이 핵심 전략 과제다."
        ),
        "key_assets": ["제주 드림타워 복합리조트", "그랜드 하얏트 제주", "드림타워 카지노", "롯데관광 여행·크루즈"],
        "opportunities": ["제주 국제선 확대", "중국·일본 고객 회복", "호텔·카지노 교차판매", "제주 도심 랜드마크"],
        "risks": ["높은 차입·금융비용", "제주 항공 공급 변동", "카지노 매출 집중", "중국 고객과 환율 민감도"],
        "extra_sources": [
            {"label": "롯데관광개발 공식 회사정보", "url": "https://m.lottetour.com/companyinfo"},
            {"label": "롯데관광개발 IR", "url": "https://ir.lottetour.com/"},
        ],
    },
}

REPORT_NUMBERS = {
    "파라다이스": "20260319001270",
    "GKL": "20260608000223",
    "강원랜드": "20260323000917",
    "롯데관광개발": "20260319000832",
}

FINANCIAL_ACCOUNTS = {
    "매출액": "revenue",
    "영업수익": "revenue",
    "영업이익": "operating_profit",
    "영업이익(손실)": "operating_profit",
    "당기순이익": "net_income",
    "당기순이익(손실)": "net_income",
    "연결당기순이익": "net_income",
    "자산총계": "assets",
    "부채총계": "liabilities",
    "자본총계": "equity",
}


def _dart_get(path, **params):
    response = requests.get(
        f"https://opendart.fss.or.kr/api/{path}",
        params={"crtfc_key": config.DART_API_KEY, **params},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "000":
        raise RuntimeError(f"DART {path}: {payload.get('status')} {payload.get('message')}")
    return payload


def _financials(corp_code):
    payload = _dart_get(
        "fnlttSinglAcnt.json",
        corp_code=corp_code,
        bsns_year="2025",
        reprt_code="11011",
        fs_div="CFS",
    )
    result = {}
    for row in payload.get("list", []):
        name = row.get("account_nm")
        key = FINANCIAL_ACCOUNTS.get(name)
        if key and key not in result:
            raw = (row.get("thstrm_amount") or "").replace(",", "")
            try:
                amount = int(raw)
            except ValueError:
                amount = None
            result[key] = amount
    return result


def run():
    if not config.DART_API_KEY:
        raise RuntimeError("DART_API_KEY가 필요합니다.")
    connection = dashboard_db()
    try:
        companies = queries.list_monitored_companies(connection)
        now = now_kst().isoformat()
        for company in companies:
            name = company["name"]
            curated = CURATED.get(name)
            if not curated:
                continue
            overview = _dart_get("company.json", corp_code=company["dart_corp_code"])
            report_no = REPORT_NUMBERS[name]
            sources = [
                {
                    "label": "DART 2025 사업보고서",
                    "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={report_no}",
                },
                {
                    "label": "DART 기업개황",
                    "url": f"https://dart.fss.or.kr/dsae001/selectPopup.ax?selectKey={company['dart_corp_code']}",
                },
                *curated["extra_sources"],
            ]
            website = (overview.get("hm_url") or "").strip()
            if website and not website.startswith(("http://", "https://")):
                website = f"https://{website}"
            queries.upsert_company_research(
                connection,
                name,
                dart_corp_code=company["dart_corp_code"],
                stock_code=overview.get("stock_code"),
                legal_name=overview.get("corp_name"),
                legal_name_eng=overview.get("corp_name_eng"),
                ceo_names=overview.get("ceo_nm"),
                headquarters=overview.get("adres"),
                established_date=overview.get("est_dt"),
                fiscal_month=overview.get("acc_mt"),
                website_url=website,
                ir_url=(overview.get("ir_url") or "").strip(),
                business_summary=curated["business_summary"],
                strategy_summary=curated["strategy_summary"],
                key_assets_json=json.dumps(curated["key_assets"], ensure_ascii=False),
                opportunities_json=json.dumps(curated["opportunities"], ensure_ascii=False),
                risks_json=json.dumps(curated["risks"], ensure_ascii=False),
                financials_json=json.dumps(_financials(company["dart_corp_code"]), ensure_ascii=False),
                sources_json=json.dumps(sources, ensure_ascii=False),
                source_period="2025 연결 사업보고서",
                researched_at=now,
                updated_at=now,
            )
            print(f"updated: {name}")
    finally:
        connection.close()


if __name__ == "__main__":
    run()

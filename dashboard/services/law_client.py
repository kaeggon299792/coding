"""
국가법령정보센터 Open API 클라이언트 (https://open.law.go.kr).

주의(중요한 범위 한계): 이 Open API는 "현행법령/연혁법령"(공포·시행된 법령
원문과 개정 이력)을 제공한다. 국회 의안정보시스템처럼 "입법예고 → 발의 →
상임위 심사 → 본회의 의결 → 공포" 단계의 법안 진행 상황을 알려주는 API가
아니다. 그래서 이 클라이언트는 "공포된 법령 원문이 이전 스냅샷과 달라졌는지"만
감지할 수 있고, 발의/심사 중인 법안의 진행 단계까지는 추적하지 못한다 - 그
부분은 README에 다음 단계 과제로 명시한다.

실제 키로 검증 완료(search_law는 정상 동작 확인). 다만 lawService.do(본문 조회)는
PythonAnywhere 환경에서 응답이 청크 단위로 아주 느리게 내려오는 경우가 있어,
일반 requests timeout으로는 안 막히는 것을 확인했다 - http_utils의 하드
타임아웃 래퍼를 사용해 우회한다.
"""

import hashlib
import logging

import requests

import config
from services.http_utils import HardTimeoutError, get_with_hard_timeout

logger = logging.getLogger("dashboard")

_API_BASE = "https://www.law.go.kr/DRF"

STATUS_LABELS = {
    "in_force": "시행 중",
    "amended_pending": "공포됨(시행 예정)",
    "unknown": "확인 필요",
}


def _get(path, params):
    if not (config.LAW_API_OC and config.LAW_API_KEY):
        return {"ok": False, "error": "LAW_API_OC / LAW_API_KEY가 설정되지 않았습니다."}

    request_params = dict(params)
    request_params["OC"] = config.LAW_API_OC
    # 국가법령정보센터 Open API는 서비스별로 인증키 파라미터명이 다를 수 있어
    # 안전하게 두 이름 모두 전달한다(문서상 elm 서비스 일부는 별도 key 파라미터 요구).
    request_params.setdefault("key", config.LAW_API_KEY)

    try:
        response = get_with_hard_timeout(
            f"{_API_BASE}/{path}",
            hard_timeout_seconds=config.LAW_REQUEST_TIMEOUT_SECONDS,
            params=request_params,
            timeout=config.LAW_REQUEST_TIMEOUT_SECONDS,
        )
    except HardTimeoutError as error:
        logger.error("법령정보 API 응답 지연(%s): %s", path, error)
        return {"ok": False, "error": str(error)}
    except requests.RequestException as error:
        logger.error("법령정보 API 호출 실패(%s): %s", path, type(error).__name__)
        return {"ok": False, "error": f"네트워크 오류: {type(error).__name__}"}

    if response.status_code != 200:
        return {"ok": False, "error": f"HTTP {response.status_code}"}

    try:
        data = response.json()
    except ValueError:
        return {"ok": False, "error": "응답이 JSON 형식이 아닙니다(키 오류 시 HTML 오류 페이지가 올 수 있음)."}

    return {"ok": True, "data": data}


def search_law(law_name):
    """법령명으로 검색해 법령ID/법령일련번호(MST) 후보를 찾는다."""
    result = _get("lawSearch.do", {"target": "law", "type": "JSON", "query": law_name})
    if not result.get("ok"):
        return result

    data = result["data"]
    law_search = data.get("LawSearch", data)
    laws = law_search.get("law", [])
    if isinstance(laws, dict):
        laws = [laws]

    candidates = [
        {
            "law_name": item.get("법령명한글") or item.get("법령명"),
            "law_id": item.get("법령ID"),
            "mst": item.get("법령일련번호"),
            "promulgation_date": item.get("공포일자"),
            "effective_date": item.get("시행일자"),
        }
        for item in laws
    ]
    return {"ok": True, "candidates": candidates}


def select_exact_candidate(candidates, law_name):
    """검색 결과에서 요청한 법령명과 정확히 일치하는 현행본을 선택한다."""
    expected = "".join(str(law_name or "").split())
    exact_matches = [
        candidate
        for candidate in candidates or []
        if "".join(str(candidate.get("law_name") or "").split()) == expected
        and candidate.get("mst")
    ]
    if not exact_matches:
        return None

    # API가 연혁을 함께 반환하는 경우 공포일자/시행일자가 가장 최신인 항목을 쓴다.
    return max(
        exact_matches,
        key=lambda candidate: (
            str(candidate.get("promulgation_date") or ""),
            str(candidate.get("effective_date") or ""),
            str(candidate.get("mst") or ""),
        ),
    )


def get_law_text(mst):
    """법령 본문(조문 포함)을 조회한다."""
    result = _get("lawService.do", {"target": "law", "type": "JSON", "MST": mst})
    if not result.get("ok"):
        return result
    return {"ok": True, "law": result["data"]}


def compute_snapshot_hash(law_data):
    """조문 텍스트만 뽑아 해시를 만든다 - 이전 스냅샷과 비교해 변경 여부를 판단한다."""
    try:
        articles = (law_data.get("법령", {}).get("조문", {}) or {}).get("조문단위", [])
        if isinstance(articles, dict):
            articles = [articles]
        text_parts = [
            f"{a.get('조문번호', '')}{a.get('조문제목', '')}{a.get('조문내용', '')}" for a in articles
        ]
    except AttributeError:
        text_parts = [str(law_data)]

    joined = "\n".join(text_parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def extract_dates(law_data):
    basic = law_data.get("법령", {}).get("기본정보", {}) if isinstance(law_data, dict) else {}
    return {
        "promulgation_date": basic.get("공포일자"),
        "effective_date": basic.get("시행일자"),
    }

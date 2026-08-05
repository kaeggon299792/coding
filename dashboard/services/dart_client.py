"""
DART 공시통합정보 OpenAPI 클라이언트 (https://opendart.fss.or.kr).

실제 키로 검증 완료(search_disclosures, corpCode.xml 조회 모두 실사용 확인).
corpCode.xml처럼 큰 응답은 PythonAnywhere 환경에서 청크 단위로 아주 느리게
내려오며 requests의 timeout으로는 안 막히는 경우가 있어, http_utils의 하드
타임아웃 래퍼를 사용한다.

DART 서버 연결 실패/키 오류가 대시보드 전체 장애로 번지지 않도록, 모든 함수는
예외를 밖으로 던지지 않고 {"ok": False, "error": ...} 형태로 실패를 반환한다.
"""

import io
import logging
import zipfile

import requests
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

import config
from services.http_utils import HardTimeoutError, get_with_hard_timeout

logger = logging.getLogger("dashboard")

_API_BASE = "https://opendart.fss.or.kr/api"

# DART 공시유형(pblntf_ty) 코드 - 필요한 만큼만 참고용으로 남겨둔다.
DISCLOSURE_TYPE_LABELS = {
    "A": "정기공시",
    "B": "주요사항보고",
    "C": "발행공시",
    "D": "지분공시",
    "E": "기타공시",
    "F": "외부감사관련",
    "G": "펀드공시",
    "H": "자산유동화",
    "I": "거래소공시",
    "J": "공정위공시",
}


def _get(endpoint, params):
    if not config.DART_API_KEY:
        return {"ok": False, "error": "DART_API_KEY가 설정되지 않았습니다."}

    request_params = dict(params)
    request_params["crtfc_key"] = config.DART_API_KEY

    try:
        response = get_with_hard_timeout(
            f"{_API_BASE}/{endpoint}",
            hard_timeout_seconds=config.DART_REQUEST_TIMEOUT_SECONDS,
            params=request_params,
            timeout=config.DART_REQUEST_TIMEOUT_SECONDS,
        )
    except HardTimeoutError as error:
        logger.error("DART API 응답 지연(%s): %s", endpoint, error)
        return {"ok": False, "error": str(error)}
    except requests.RequestException as error:
        logger.error("DART API 호출 실패(%s): %s", endpoint, type(error).__name__)
        return {"ok": False, "error": f"네트워크 오류: {type(error).__name__}"}

    if response.status_code != 200:
        return {"ok": False, "error": f"HTTP {response.status_code}"}

    try:
        data = response.json()
    except ValueError:
        return {"ok": False, "error": "응답이 JSON 형식이 아닙니다(원문 조회 등 바이너리 응답일 수 있음)."}

    status = data.get("status")
    if status != "000":
        # DART 오류 코드: 010=등록되지않은키, 011=사용한도초과, 013=조회된데이터없음 등
        message = data.get("message", "알 수 없는 오류")
        if status == "013":
            return {"ok": True, "list": [], "note": message}
        return {"ok": False, "error": f"[{status}] {message}"}

    return {"ok": True, **data}


def search_disclosures(corp_code=None, start_date=None, end_date=None, page_no=1, page_count=100,
                        pblntf_ty=None):
    """공시검색(list.json). start_date/end_date는 YYYYMMDD 형식."""
    params = {"page_no": page_no, "page_count": page_count}
    if corp_code:
        params["corp_code"] = corp_code
    if start_date:
        params["bgn_de"] = start_date
    if end_date:
        params["end_de"] = end_date
    if pblntf_ty:
        params["pblntf_ty"] = pblntf_ty

    return _get("list.json", params)


def build_dart_link(rcept_no):
    return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


def is_important_disclosure(report_nm):
    if not report_nm:
        return False
    return any(keyword in report_nm for keyword in config.DART_IMPORTANT_KEYWORDS)


def fetch_corp_code_map():
    """고유번호 전체 목록(corpCode.xml, zip)을 내려받아 {회사명: corp_code} 매핑을 만든다.

    관심기업 등록 화면에서 회사명으로 corp_code를 찾을 때만 호출한다(무거운 작업이라
    수시 폴링에서는 쓰지 않는다).
    """
    if not config.DART_API_KEY:
        return {"ok": False, "error": "DART_API_KEY가 설정되지 않았습니다."}

    try:
        response = get_with_hard_timeout(
            f"{_API_BASE}/corpCode.xml",
            hard_timeout_seconds=config.DART_CORP_CODE_TIMEOUT_SECONDS,
            params={"crtfc_key": config.DART_API_KEY},
            timeout=config.DART_CORP_CODE_TIMEOUT_SECONDS,
        )
    except HardTimeoutError as error:
        return {"ok": False, "error": str(error)}
    except requests.RequestException as error:
        return {"ok": False, "error": f"네트워크 오류: {type(error).__name__}"}

    if response.status_code != 200:
        return {"ok": False, "error": f"HTTP {response.status_code}"}

    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            xml_bytes = archive.read(archive.namelist()[0])
        root = ElementTree.fromstring(xml_bytes)
    except (zipfile.BadZipFile, ElementTree.ParseError, DefusedXmlException) as error:
        return {"ok": False, "error": f"고유번호 목록 파싱 실패: {error} (API 키 오류 응답일 수 있음)"}

    companies = []
    for entry in root.findall("list"):
        companies.append(
            {
                "corp_code": (entry.findtext("corp_code") or "").strip(),
                "corp_name": (entry.findtext("corp_name") or "").strip(),
                "stock_code": (entry.findtext("stock_code") or "").strip(),
            }
        )
    return {"ok": True, "companies": companies}

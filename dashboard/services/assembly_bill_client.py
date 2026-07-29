"""열린국회정보 의안정보 통합 API(ALLBILLV2) 클라이언트."""

import logging

import requests

import config
from services.http_utils import HardTimeoutError, get_with_hard_timeout

logger = logging.getLogger("dashboard")

API_URL = "https://open.assembly.go.kr/portal/openapi/ALLBILLV2"


def _rows_from_response(data):
    payload = data.get("ALLBILLV2", [])
    if not isinstance(payload, list):
        return []
    for section in payload:
        if isinstance(section, dict) and isinstance(section.get("row"), list):
            return section["row"]
    return []


def search_bills(keyword, era=None):
    """의안명에 keyword가 포함된 의안을 조회한다."""
    if not config.ASSEMBLY_API_KEY:
        return {"ok": False, "error": "ASSEMBLY_API_KEY가 설정되지 않았습니다."}

    params = {
        "KEY": config.ASSEMBLY_API_KEY,
        "Type": "json",
        "pIndex": 1,
        "pSize": 100,
        "ERACO": era or config.ASSEMBLY_ERA,
        "BILL_NM": keyword,
    }
    try:
        response = get_with_hard_timeout(
            API_URL,
            hard_timeout_seconds=config.ASSEMBLY_REQUEST_TIMEOUT_SECONDS,
            params=params,
            timeout=config.ASSEMBLY_REQUEST_TIMEOUT_SECONDS,
        )
    except HardTimeoutError as error:
        return {"ok": False, "error": str(error)}
    except requests.RequestException as error:
        logger.error("국회 의안정보 API 호출 실패: %s", type(error).__name__)
        return {"ok": False, "error": f"네트워크 오류: {type(error).__name__}"}

    if response.status_code != 200:
        return {"ok": False, "error": f"HTTP {response.status_code}"}
    try:
        data = response.json()
    except ValueError:
        return {"ok": False, "error": "의안정보 API 응답이 JSON 형식이 아닙니다."}
    return {"ok": True, "bills": _rows_from_response(data)}


def normalize_bill(row, matched_keyword):
    """API 행을 DB 저장용 공통 필드로 변환한다."""
    return {
        "bill_id": row.get("BILL_ID"),
        "bill_no": row.get("BILL_NO"),
        "era": row.get("ERACO"),
        "bill_kind": row.get("BILL_KND"),
        "bill_name": row.get("BILL_NM"),
        "proposer_kind": row.get("PPSR_KND"),
        "proposer_name": row.get("PPSR_NM"),
        "proposed_date": row.get("PPSL_DT"),
        "committee_name": row.get("JRCMIT_NM"),
        "committee_result": row.get("JRCMIT_PROC_RSLT"),
        "plenary_result": row.get("RGS_CONF_RSLT"),
        "process_stage": row.get("PROC_STAGE_CD"),
        "pass_status": row.get("PASSGUBN"),
        "link_url": row.get("LINK_URL"),
        "pdf_url": row.get("PDF_URL1") or row.get("PDF_URL2"),
        "matched_keyword": matched_keyword,
    }

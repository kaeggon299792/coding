"""열린국회정보 의안정보 통합 API(ALLBILLV2) 클라이언트."""

import logging
from io import BytesIO
from zipfile import BadZipFile, ZipFile

import requests
from pypdf import PdfReader
from pypdf.errors import PdfReadError

import config
from services.http_utils import HardTimeoutError, get_with_hard_timeout

logger = logging.getLogger("dashboard")

API_URL = "https://open.assembly.go.kr/portal/openapi/ALLBILLV2"
DETAIL_PAGE_URL = "https://likms.assembly.go.kr/bill/bi/billDetailPage.do"
DETAIL_ZIP_URL = "https://likms.assembly.go.kr/bill/bi/bill/detail/downloadDtlZip.do"


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


def fetch_bill_source_text(bill_id, bill_kind="법률안"):
    """국회 의안 원문 ZIP의 PDF에서 AI 분석용 텍스트를 추출한다."""
    try:
        session = requests.Session()
        session.get(
            DETAIL_PAGE_URL,
            params={"billId": bill_id},
            timeout=config.ASSEMBLY_REQUEST_TIMEOUT_SECONDS,
        )
        response = session.post(
            DETAIL_ZIP_URL,
            data={"billId": bill_id, "billCd": bill_kind or "법률안"},
            timeout=config.ASSEMBLY_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        with ZipFile(BytesIO(response.content)) as archive:
            pdf_names = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
            if not pdf_names:
                return {"ok": False, "error": "의안 원문 PDF를 찾지 못했습니다."}
            pdf_bytes = archive.read(pdf_names[0])
        reader = PdfReader(BytesIO(pdf_bytes))
        chunks = []
        char_count = 0
        for page in reader.pages[:30]:
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            remaining = config.ASSEMBLY_BILL_TEXT_MAX_CHARS - char_count
            if remaining <= 0:
                break
            chunks.append(text[:remaining])
            char_count += len(chunks[-1])
        extracted = "\n\n".join(chunks).strip()
        if not extracted:
            return {"ok": False, "error": "의안 원문에서 텍스트를 추출하지 못했습니다."}
        return {"ok": True, "text": extracted, "source": "국회 의안 원문 PDF"}
    except (requests.RequestException, BadZipFile, PdfReadError, KeyError, ValueError) as error:
        logger.error("의안 원문 수집 실패(%s): %s", bill_id, type(error).__name__)
        return {"ok": False, "error": f"의안 원문 수집 실패: {type(error).__name__}"}

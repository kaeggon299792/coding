"""법제처 국민참여입법센터 정부입법예고 REST 클라이언트."""

import logging
import xml.etree.ElementTree as ET

import requests

import config
from services.http_utils import HardTimeoutError, get_with_hard_timeout

logger = logging.getLogger("dashboard")

API_URL = "https://www.lawmaking.go.kr/rest/ogLmPp.xml"
DETAIL_URL = "https://opinion.lawmaking.go.kr/gcom/ogLmPp/{notice_id}"


def _text(node, name):
    child = node.find(name)
    return (child.text or "").strip() if child is not None else ""


def _notice_nodes(root):
    candidates = root.findall(".//ogLmPp")
    if candidates:
        return candidates
    return [
        node for node in root.iter()
        if node.find("ogLmPpSeq") is not None and node.find("lsNm") is not None
    ]


def search_notices(keyword, status=None):
    if not config.LAWMAKING_API_OC:
        return {"ok": False, "error": "LAWMAKING_API_OC가 설정되지 않았습니다."}
    params = {"OC": config.LAWMAKING_API_OC, "lsNm": keyword}
    if status is not None:
        params["diff"] = str(status)
    try:
        response = get_with_hard_timeout(
            API_URL,
            hard_timeout_seconds=config.LAWMAKING_REQUEST_TIMEOUT_SECONDS,
            params=params,
            timeout=config.LAWMAKING_REQUEST_TIMEOUT_SECONDS,
        )
    except HardTimeoutError as error:
        return {"ok": False, "error": str(error)}
    except requests.RequestException as error:
        logger.error("정부입법예고 API 호출 실패: %s", type(error).__name__)
        return {"ok": False, "error": f"네트워크 오류: {type(error).__name__}"}
    if response.status_code != 200:
        return {"ok": False, "error": f"HTTP {response.status_code}"}
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError:
        return {"ok": False, "error": "정부입법예고 API 응답이 XML 형식이 아닙니다."}
    return_code = _text(root, "retMsg") or _text(root, "resultCode")
    if return_code and return_code not in {"0", "00", "200"}:
        return {"ok": False, "error": f"API 인증 또는 요청 오류({return_code})"}
    return {"ok": True, "notices": _notice_nodes(root)}


def normalize_notice(node, matched_keyword):
    notice_id = _text(node, "ogLmPpSeq")
    view_count = _text(node, "readCnt")
    return {
        "notice_id": notice_id,
        "notice_name": _text(node, "lsNm"),
        "law_type": _text(node, "lsClsNm"),
        "ministry_name": _text(node, "asndOfiNm"),
        "announcement_no": _text(node, "pntcNo"),
        "announcement_date": _text(node, "pntcDt"),
        "start_date": _text(node, "stYd"),
        "end_date": _text(node, "edYd"),
        "attachment_name": _text(node, "FileName"),
        "attachment_url": _text(node, "FileDownLink"),
        "detail_url": DETAIL_URL.format(notice_id=notice_id),
        "view_count": int(view_count) if view_count.isdigit() else None,
        "announcement_type": _text(node, "announceType"),
        "matched_keyword": matched_keyword,
    }

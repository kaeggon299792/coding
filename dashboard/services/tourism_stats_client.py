"""한국문화관광연구원 방한외래관광객통계 Open API 클라이언트."""

import logging
import xml.etree.ElementTree as ElementTree
from datetime import date

import requests

import config

logger = logging.getLogger("tourism_stats")

API_URL = (
    "http://openapi.tour.go.kr/openapi/service/EdrcntTourismStatsService/"
    "getForeignTuristStatsList"
)
NATIONALITY_CODES = {
    "중국": "112",
    "일본": "130",
    "대만": "113",
    "몽골": "145",
}
MAX_ROWS = 30000


def fetch_month(ym, nat_cd=None):
    if not config.TOURISM_API_KEY:
        return {"ok": False, "error": "TOURISM_API_KEY가 설정되지 않았습니다."}
    params = {
        "YM": ym,
        "serviceKey": config.TOURISM_API_KEY,
        "numOfRows": MAX_ROWS,
        "pageNo": 1,
    }
    if nat_cd:
        params["NAT_CD"] = nat_cd
    try:
        response = requests.get(
            API_URL,
            params=params,
            timeout=(8, config.TOURISM_REQUEST_TIMEOUT_SECONDS),
            headers={"User-Agent": "ParadiseManagementDashboard/1.0"},
        )
        response.raise_for_status()
    except requests.RequestException as error:
        logger.error("관광 통계 API 호출 실패(YM=%s): %s", ym, type(error).__name__)
        return {"ok": False, "error": f"네트워크 오류: {type(error).__name__}"}

    try:
        root = ElementTree.fromstring(response.content)
    except ElementTree.ParseError:
        return {"ok": False, "error": "API 응답이 올바른 XML이 아닙니다."}
    result_code = (root.findtext(".//resultCode") or "").strip()
    if result_code not in ("", "0000"):
        return {
            "ok": False,
            "error": (root.findtext(".//resultMsg") or result_code).strip(),
        }

    total_count = int(root.findtext(".//totalCount") or 0)
    if total_count > MAX_ROWS:
        return {"ok": False, "error": f"응답 건수 {total_count:,}건이 수집 상한을 초과했습니다."}
    visitor_count = 0
    by_nationality = {}
    for item in root.findall(".//item"):
        try:
            count = int(item.findtext("num") or 0)
        except ValueError:
            continue
        visitor_count += count
        code = (item.findtext("natCd") or "").strip()
        if code:
            by_nationality[code] = by_nationality.get(code, 0) + count
    return {
        "ok": True,
        "visitor_count": visitor_count,
        "total_count": total_count,
        "by_nationality": by_nationality,
    }


def find_latest_available_ym(max_lookback=6):
    year, month = date.today().year, date.today().month
    for _ in range(max_lookback):
        ym = f"{year}{month:02d}"
        result = fetch_month(ym, NATIONALITY_CODES["중국"])
        if result.get("ok") and result.get("visitor_count", 0) > 0:
            return ym
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return None


def get_bucket_totals(ym):
    grand_total = fetch_month(ym)
    if not grand_total.get("ok"):
        return grand_total
    buckets, named_total = {}, 0
    totals_by_code = grand_total.get("by_nationality") or {}
    for label, code in NATIONALITY_CODES.items():
        buckets[label] = totals_by_code.get(code, 0)
        named_total += buckets[label]
    buckets["기타"] = max(grand_total["visitor_count"] - named_total, 0)
    return {"ok": True, "buckets": buckets}

"""오피넷 유가와 한국수출입은행 환율 API 클라이언트."""
from datetime import datetime, timedelta
import requests
import config
from services.http_utils import HardTimeoutError, get_with_hard_timeout

OPINET_URL = "https://www.opinet.co.kr/api/avgRecentPrice.do"
EXCHANGE_URL = "https://oapi.koreaexim.go.kr/site/program/financial/exchangeJSON"
OILS = {"B027": ("OIL_B027", "보통휘발유"), "D047": ("OIL_D047", "자동차용경유"), "K015": ("OIL_K015", "자동차용부탄")}
FX = {"USD": ("FX_USD", "미국 달러"), "JPY(100)": ("FX_JPY100", "일본 엔(100)"), "CNH": ("FX_CNH", "중국 위안"), "EUR": ("FX_EUR", "유로")}

def _number(value):
    try: return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError): return None

def fetch_oil():
    if not config.OPINET_API_KEY: return {"items": [], "errors": ["OPINET_API_KEY 미설정"]}
    try:
        response = get_with_hard_timeout(
            OPINET_URL,
            hard_timeout_seconds=config.ECONOMIC_DATA_REQUEST_TIMEOUT_SECONDS,
            params={"out": "json", "code": config.OPINET_API_KEY},
            timeout=config.ECONOMIC_DATA_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        rows = ((response.json().get("RESULT") or {}).get("OIL") or [])
    except (requests.RequestException, ValueError, HardTimeoutError) as error:
        return {"items": [], "errors": [f"오피넷 API 오류: {type(error).__name__}"]}
    items = []
    for row in rows:
        mapping, value = OILS.get(str(row.get("PRODCD") or "")), _number(row.get("PRICE"))
        date = str(row.get("DATE") or row.get("TRADE_DT") or "").replace("-", "")
        if mapping and value is not None and len(date) == 8:
            items.append({"series_code":mapping[0],"observation_date":date,"label":mapping[1],"category":"oil","value":value,"unit":"원/L","source":"한국석유공사 오피넷"})
    return {"items": items, "errors": [] if items else ["오피넷 데이터가 비어 있습니다."]}

def fetch_exchange(days=35):
    if not config.KOREAEXIM_API_KEY: return {"items": [], "errors": ["KOREAEXIM_API_KEY 미설정"]}
    items, errors, today = [], [], datetime.now(config.KST).date()
    for offset in range(days):
        target = today - timedelta(days=offset)
        if target.weekday() >= 5: continue
        date = target.strftime("%Y%m%d")
        try:
            response = get_with_hard_timeout(EXCHANGE_URL, hard_timeout_seconds=config.ECONOMIC_DATA_REQUEST_TIMEOUT_SECONDS, params={"authkey":config.KOREAEXIM_API_KEY,"searchdate":date,"data":"AP01"}, timeout=config.ECONOMIC_DATA_REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status(); rows = response.json()
        except (requests.RequestException, ValueError, HardTimeoutError) as error:
            errors.append(f"{date}: {type(error).__name__}"); continue
        if not isinstance(rows, list): continue
        for row in rows:
            mapping, value = FX.get(str(row.get("cur_unit") or "")), _number(row.get("deal_bas_r"))
            if mapping and value is not None:
                items.append({"series_code":mapping[0],"observation_date":date,"label":mapping[1],"category":"exchange","value":value,"unit":"원","source":"한국수출입은행"})
    return {"items": items, "errors": errors}

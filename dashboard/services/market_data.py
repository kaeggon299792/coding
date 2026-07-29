"""금융위원회 주식·지수 시세 API 클라이언트."""

import logging
from datetime import datetime, timedelta

import requests

import config
from services.http_utils import HardTimeoutError, get_with_hard_timeout

logger = logging.getLogger("dashboard")

STOCK_URL = (
    "https://apis.data.go.kr/1160100/service/"
    "GetStockSecuritiesInfoService/getStockPriceInfo"
)
INDEX_URL = (
    "https://apis.data.go.kr/1160100/service/"
    "GetMarketIndexInfoService/getStockMarketIndex"
)

TRACKED_STOCKS = (
    {"symbol": "034230", "name": "파라다이스", "market": "KOSDAQ"},
    {"symbol": "114090", "name": "GKL", "market": "KOSPI"},
    {"symbol": "035250", "name": "강원랜드", "market": "KOSPI"},
    {"symbol": "032350", "name": "롯데관광개발", "market": "KOSPI"},
)


def _items(data):
    body = (data.get("response") or {}).get("body") or {}
    items = body.get("items") or {}
    rows = items.get("item") if isinstance(items, dict) else []
    if isinstance(rows, dict):
        rows = [rows]
    return rows if isinstance(rows, list) else []


def _get(url, params):
    if not config.MARKET_DATA_API_KEY:
        return {"ok": False, "error": "MARKET_DATA_API_KEY가 설정되지 않았습니다."}
    request_params = {
        "serviceKey": config.MARKET_DATA_API_KEY,
        "numOfRows": 10,
        "pageNo": 1,
        "resultType": "json",
        **params,
    }
    try:
        response = get_with_hard_timeout(
            url,
            hard_timeout_seconds=config.MARKET_DATA_REQUEST_TIMEOUT_SECONDS,
            params=request_params,
            timeout=config.MARKET_DATA_REQUEST_TIMEOUT_SECONDS,
        )
    except HardTimeoutError as error:
        return {"ok": False, "error": str(error)}
    except requests.RequestException as error:
        return {"ok": False, "error": f"네트워크 오류: {type(error).__name__}"}
    if response.status_code == 401:
        return {"ok": False, "error": "공공데이터 API 활용 승인이 필요합니다."}
    if response.status_code != 200:
        return {"ok": False, "error": f"HTTP {response.status_code}"}
    try:
        data = response.json()
    except ValueError:
        return {"ok": False, "error": "시세 API 응답이 JSON 형식이 아닙니다."}
    rows = _items(data)
    if not rows:
        header = (data.get("response") or {}).get("header") or {}
        return {"ok": False, "error": header.get("resultMsg") or "시세 데이터가 없습니다."}
    return {"ok": True, "rows": rows}


def _number(value, integer=False):
    if value in (None, ""):
        return None
    try:
        return int(float(value)) if integer else float(value)
    except (TypeError, ValueError):
        return None


def _latest(rows):
    return max(rows, key=lambda row: str(row.get("basDt") or ""))


def fetch_stock(stock):
    begin_date = (datetime.now(config.KST) - timedelta(days=14)).strftime("%Y%m%d")
    result = _get(
        STOCK_URL,
        {"likeSrtnCd": stock["symbol"], "beginBasDt": begin_date},
    )
    if not result.get("ok"):
        return result
    row = _latest(result["rows"])
    return {
        "ok": True,
        "quote": {
            "symbol": stock["symbol"],
            "name": stock["name"],
            "asset_type": "stock",
            "market": row.get("mrktCtg") or stock["market"],
            "base_date": row.get("basDt"),
            "close_price": _number(row.get("clpr"), integer=True),
            "change_value": _number(row.get("vs"), integer=True),
            "change_rate": _number(row.get("fltRt")),
            "open_price": _number(row.get("mkp"), integer=True),
            "high_price": _number(row.get("hipr"), integer=True),
            "low_price": _number(row.get("lopr"), integer=True),
            "volume": _number(row.get("trqu"), integer=True),
        },
    }


def fetch_kospi():
    begin_date = (datetime.now(config.KST) - timedelta(days=14)).strftime("%Y%m%d")
    result = _get(
        INDEX_URL,
        {"likeIdxNm": "코스피", "beginBasDt": begin_date},
    )
    if not result.get("ok"):
        return result
    rows = [row for row in result["rows"] if (row.get("idxNm") or "").strip() == "코스피"]
    row = _latest(rows or result["rows"])
    return {
        "ok": True,
        "quote": {
            "symbol": "KOSPI",
            "name": "KOSPI",
            "asset_type": "index",
            "market": "KOSPI",
            "base_date": row.get("basDt"),
            "close_price": _number(row.get("clpr")),
            "change_value": _number(row.get("vs")),
            "change_rate": _number(row.get("fltRt")),
            "open_price": _number(row.get("mkp")),
            "high_price": _number(row.get("hipr")),
            "low_price": _number(row.get("lopr")),
            "volume": _number(row.get("trqu"), integer=True),
        },
    }


def fetch_dashboard_quotes():
    results = [fetch_kospi(), *(fetch_stock(stock) for stock in TRACKED_STOCKS)]
    return {
        "quotes": [result["quote"] for result in results if result.get("ok")],
        "errors": [result.get("error") for result in results if not result.get("ok")],
    }

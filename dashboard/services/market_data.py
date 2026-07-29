"""금융위원회 주식·지수 시세 API 클라이언트."""

import logging
from datetime import datetime, timedelta, timezone

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

GLOBAL_STOCKS = (
    {"symbol": "1928.HK", "name": "Sands China", "market": "HKEX", "currency": "HKD"},
    {"symbol": "0027.HK", "name": "Galaxy Entertainment", "market": "HKEX", "currency": "HKD"},
    {"symbol": "0880.HK", "name": "SJM Holdings", "market": "HKEX", "currency": "HKD"},
    {"symbol": "MLCO", "name": "Melco Resorts & Entertainment", "market": "NASDAQ", "currency": "USD"},
)
YAHOO_CHART_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"


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
        "numOfRows": 40,
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


def _history(rows):
    return [
        {
            "base_date": row.get("basDt"),
            "close_price": _number(row.get("clpr")),
        }
        for row in sorted(rows, key=lambda item: str(item.get("basDt") or ""))
        if row.get("basDt") and _number(row.get("clpr")) is not None
    ]


def fetch_stock(stock):
    begin_date = (datetime.now(config.KST) - timedelta(days=50)).strftime("%Y%m%d")
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
            "market_cap": _number(row.get("mrktTotAmt"), integer=True),
            "history": _history(result["rows"]),
        },
    }


def fetch_kospi():
    begin_date = (datetime.now(config.KST) - timedelta(days=50)).strftime("%Y%m%d")
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
            "market_cap": None,
            "history": _history(rows or result["rows"]),
        },
    }


def fetch_global_stock(stock):
    """API 키 없이 Yahoo Finance 일별 차트 응답을 정규화한다."""
    try:
        response = get_with_hard_timeout(
            YAHOO_CHART_URL.format(symbol=stock["symbol"]),
            hard_timeout_seconds=config.MARKET_DATA_REQUEST_TIMEOUT_SECONDS,
            params={"range": "1mo", "interval": "1d", "events": "div,splits"},
            headers={"User-Agent": "Mozilla/5.0 (PARADISE market dashboard)"},
            timeout=config.MARKET_DATA_REQUEST_TIMEOUT_SECONDS,
        )
    except HardTimeoutError as error:
        return {"ok": False, "symbol": stock["symbol"], "error": str(error)}
    except requests.RequestException as error:
        return {
            "ok": False,
            "symbol": stock["symbol"],
            "error": f"Yahoo Finance 네트워크 오류: {type(error).__name__}",
        }
    if response.status_code != 200:
        return {
            "ok": False,
            "symbol": stock["symbol"],
            "error": f"Yahoo Finance HTTP {response.status_code}",
        }
    try:
        chart = (response.json().get("chart") or {})
        result = (chart.get("result") or [None])[0]
    except (ValueError, AttributeError, IndexError):
        result = None
    if not result:
        return {
            "ok": False,
            "symbol": stock["symbol"],
            "error": "Yahoo Finance 시세 데이터가 없습니다.",
        }

    meta = result.get("meta") or {}
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quote_rows = (indicators.get("quote") or [{}])[0]
    adjusted = ((indicators.get("adjclose") or [{}])[0].get("adjclose") or [])
    closes = quote_rows.get("close") or []
    history = []
    for index, timestamp in enumerate(timestamps):
        close = adjusted[index] if index < len(adjusted) else (
            closes[index] if index < len(closes) else None
        )
        if close is None:
            continue
        history.append(
            {
                "base_date": datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y%m%d"),
                "close_price": round(float(close), 4),
            }
        )
    current = _number(meta.get("regularMarketPrice"))
    previous = _number(meta.get("chartPreviousClose") or meta.get("previousClose"))
    if current is None and history:
        current = history[-1]["close_price"]
    if previous is None and len(history) > 1:
        previous = history[-2]["close_price"]
    if current is None:
        return {
            "ok": False,
            "symbol": stock["symbol"],
            "error": "Yahoo Finance 현재가가 비어 있습니다.",
        }
    change_value = current - previous if previous is not None else None
    change_rate = (
        change_value / previous * 100
        if previous not in (None, 0)
        else None
    )
    market_time = meta.get("regularMarketTime")
    base_date = (
        datetime.fromtimestamp(market_time, timezone.utc).strftime("%Y%m%d")
        if market_time
        else (history[-1]["base_date"] if history else None)
    )
    return {
        "ok": True,
        "quote": {
            "symbol": stock["symbol"],
            "name": stock["name"],
            "asset_type": "global_stock",
            "market": stock["market"],
            "currency": meta.get("currency") or stock["currency"],
            "source": "Yahoo Finance",
            "base_date": base_date,
            "close_price": current,
            "change_value": change_value,
            "change_rate": change_rate,
            "open_price": _number(meta.get("regularMarketOpen")),
            "high_price": _number(meta.get("regularMarketDayHigh")),
            "low_price": _number(meta.get("regularMarketDayLow")),
            "volume": _number(meta.get("regularMarketVolume"), integer=True),
            "market_cap": None,
            "history": history,
        },
    }


def fetch_global_quotes():
    results = [fetch_global_stock(stock) for stock in GLOBAL_STOCKS]
    return {
        "quotes": [result["quote"] for result in results if result.get("ok")],
        "errors": [
            {"symbol": result.get("symbol"), "error": result.get("error")}
            for result in results if not result.get("ok")
        ],
    }


def fetch_dashboard_quotes():
    results = [fetch_kospi(), *(fetch_stock(stock) for stock in TRACKED_STOCKS)]
    return {
        "quotes": [result["quote"] for result in results if result.get("ok")],
        "errors": [result.get("error") for result in results if not result.get("ok")],
    }

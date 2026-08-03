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
    {"symbol": "034230", "name": "파라다이스", "market": "KOSPI", "yahoo_symbol": "034230.KS"},
    {"symbol": "114090", "name": "GKL", "market": "KOSPI", "yahoo_symbol": "114090.KS"},
    {"symbol": "035250", "name": "강원랜드", "market": "KOSPI", "yahoo_symbol": "035250.KS"},
    {"symbol": "032350", "name": "롯데관광개발", "market": "KOSPI", "yahoo_symbol": "032350.KS"},
)

GLOBAL_STOCKS = (
    {"symbol": "1928.HK", "name": "Sands China", "market": "HKEX", "currency": "HKD"},
    {"symbol": "0027.HK", "name": "Galaxy Entertainment", "market": "HKEX", "currency": "HKD"},
    {"symbol": "0880.HK", "name": "SJM Holdings", "market": "HKEX", "currency": "HKD"},
    {"symbol": "MLCO", "name": "Melco Resorts & Entertainment", "market": "NASDAQ", "currency": "USD"},
)
YAHOO_CHART_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_QUOTE_SUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
YAHOO_CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"
TOSS_BASE_URL = "https://openapi.tossinvest.com"


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


def _toss_credentials_ready():
    return bool(config.TOSS_INVEST_CLIENT_ID and config.TOSS_INVEST_CLIENT_SECRET)


def _toss_access_token():
    if not _toss_credentials_ready():
        return {"ok": False, "error": "토스증권 API 인증정보가 설정되지 않았습니다."}
    try:
        response = requests.post(
            f"{TOSS_BASE_URL}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": config.TOSS_INVEST_CLIENT_ID,
                "client_secret": config.TOSS_INVEST_CLIENT_SECRET,
            },
            timeout=config.MARKET_DATA_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        return {"ok": False, "error": f"토스증권 인증 네트워크 오류: {type(error).__name__}"}
    if response.status_code != 200:
        return {"ok": False, "error": f"토스증권 인증 HTTP {response.status_code}"}
    try:
        payload = response.json()
    except ValueError:
        return {"ok": False, "error": "토스증권 인증 응답이 JSON 형식이 아닙니다."}
    result = payload.get("result") or {}
    token = payload.get("access_token") or result.get("accessToken") or result.get("access_token")
    if not token:
        return {"ok": False, "error": "토스증권 액세스 토큰이 비어 있습니다."}
    return {"ok": True, "token": token}


def _toss_candles(symbol, token, indicator=False):
    path = (
        f"/api/v1/market-indicators/{symbol}/candles"
        if indicator else "/api/v1/candles"
    )
    params = {"interval": "1d", "count": 50}
    if not indicator:
        params["symbol"] = symbol
        params["adjusted"] = "true"
    try:
        response = get_with_hard_timeout(
            f"{TOSS_BASE_URL}{path}",
            hard_timeout_seconds=config.MARKET_DATA_REQUEST_TIMEOUT_SECONDS,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=config.MARKET_DATA_REQUEST_TIMEOUT_SECONDS,
        )
    except (HardTimeoutError, requests.RequestException) as error:
        return {"ok": False, "error": f"토스증권 시세 오류: {type(error).__name__}"}
    if response.status_code != 200:
        return {"ok": False, "error": f"토스증권 시세 HTTP {response.status_code}"}
    try:
        result = response.json().get("result") or {}
    except (ValueError, AttributeError):
        return {"ok": False, "error": "토스증권 시세 응답이 JSON 형식이 아닙니다."}
    candles = result.get("candles") if isinstance(result, dict) else None
    if not isinstance(candles, list) or not candles:
        return {"ok": False, "error": "토스증권 일봉 데이터가 없습니다."}
    return {"ok": True, "candles": candles}


def _toss_quote(stock, token, indicator=False):
    result = _toss_candles(stock["symbol"], token, indicator=indicator)
    if not result.get("ok"):
        return {**result, "symbol": stock["symbol"]}
    candles = sorted(result["candles"], key=lambda item: str(item.get("timestamp") or ""))
    latest = candles[-1]
    previous = candles[-2] if len(candles) > 1 else None
    close = _number(latest.get("closePrice"))
    previous_close = _number(previous.get("closePrice")) if previous else None
    if close is None:
        return {"ok": False, "symbol": stock["symbol"], "error": "토스증권 종가가 비어 있습니다."}
    change = close - previous_close if previous_close is not None else None
    history = [
        {
            "base_date": str(item.get("timestamp") or "")[:10].replace("-", ""),
            "close_price": _number(item.get("closePrice")),
        }
        for item in candles
        if item.get("timestamp") and _number(item.get("closePrice")) is not None
    ]
    return {
        "ok": True,
        "quote": {
            "symbol": stock["symbol"], "name": stock["name"],
            "asset_type": "index" if indicator else "stock",
            "market": stock["market"],
            "base_date": str(latest.get("timestamp") or "")[:10].replace("-", ""),
            "close_price": close, "change_value": change,
            "change_rate": change / previous_close * 100 if previous_close not in (None, 0) else None,
            "open_price": _number(latest.get("openPrice")),
            "high_price": _number(latest.get("highPrice")),
            "low_price": _number(latest.get("lowPrice")),
            "volume": _number(latest.get("volume"), integer=True),
            "market_cap": None, "currency": latest.get("currency") or "KRW",
            "source": "토스증권 Open API", "history": history,
        },
    }


def fetch_toss_domestic_quotes():
    """토스증권 일봉을 보조 수집원으로 조회한다."""
    auth = _toss_access_token()
    if not auth.get("ok"):
        return {"quotes": [], "errors": [auth.get("error")]}
    kospi = {"symbol": "KOSPI", "name": "KOSPI", "market": "KOSPI"}
    results = [
        _toss_quote(kospi, auth["token"], indicator=True),
        *(_toss_quote(stock, auth["token"]) for stock in TRACKED_STOCKS),
    ]
    return {
        "quotes": [item["quote"] for item in results if item.get("ok")],
        "errors": [item.get("error") for item in results if not item.get("ok")],
    }


def _merge_domestic_quotes(primary, fallback):
    """기준일이 더 최신인 시세를 채택하고 비어 있는 필드는 다른 출처로 보완한다."""
    merged = {}
    for quote in [*fallback, *primary]:
        symbol = quote["symbol"]
        current = merged.get(symbol)
        if current is None:
            merged[symbol] = dict(quote)
            continue
        preferred, secondary = (
            (quote, current)
            if str(quote.get("base_date") or "") >= str(current.get("base_date") or "")
            else (current, quote)
        )
        combined = dict(secondary)
        combined.update({key: value for key, value in preferred.items() if value is not None})
        if preferred.get("history") and secondary.get("history"):
            history = {item["base_date"]: item for item in secondary["history"]}
            history.update({item["base_date"]: item for item in preferred["history"]})
            combined["history"] = [history[key] for key in sorted(history)]
        merged[symbol] = combined
    return list(merged.values())


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
            YAHOO_CHART_URL.format(symbol=stock.get("yahoo_symbol") or stock["symbol"]),
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
    quotes = [result["quote"] for result in results if result.get("ok")]
    market_caps = _fetch_yahoo_market_caps([quote["symbol"] for quote in quotes])
    for quote in quotes:
        quote["market_cap"] = market_caps.get(quote["symbol"])
    return {
        "quotes": quotes,
        "errors": [
            {"symbol": result.get("symbol"), "error": result.get("error")}
            for result in results if not result.get("ok")
        ],
    }


def _fetch_yahoo_market_caps(symbols):
    """Fetch market caps with Yahoo's cookie/crumb flow without adding yfinance."""
    if not symbols:
        return {}
    timeout = min(max(float(config.MARKET_DATA_REQUEST_TIMEOUT_SECONDS), 2.0), 8.0)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (CASINO IN market dashboard)"})
    try:
        session.get("https://fc.yahoo.com", timeout=timeout)
        crumb_response = session.get(YAHOO_CRUMB_URL, timeout=timeout)
        if crumb_response.status_code != 200:
            return {}
        crumb = crumb_response.text.strip()
        if not crumb or "<" in crumb:
            return {}
    except requests.RequestException:
        return {}

    market_caps = {}
    for _attempt in range(2):
        for symbol in symbols:
            if symbol in market_caps:
                continue
            try:
                response = session.get(
                    YAHOO_QUOTE_SUMMARY_URL.format(symbol=symbol),
                    params={"modules": "price", "crumb": crumb},
                    timeout=timeout,
                )
                if response.status_code != 200:
                    continue
                price = (((response.json().get("quoteSummary") or {}).get("result") or [{}])[0].get("price") or {})
                raw = (price.get("marketCap") or {}).get("raw")
                value = _number(raw, integer=True)
                if value is not None:
                    market_caps[symbol] = value
            except (requests.RequestException, ValueError, AttributeError, IndexError, TypeError):
                continue
    return market_caps


def fetch_yahoo_domestic_quotes():
    """PythonAnywhere에서 토스 인증이 차단될 때 사용하는 국내 시세 보조원."""
    stocks = [
        {"symbol": "KOSPI", "yahoo_symbol": "^KS11", "name": "KOSPI", "market": "KOSPI", "currency": "KRW"},
        *({**stock, "currency": "KRW"} for stock in TRACKED_STOCKS),
    ]
    results = [fetch_global_stock(stock) for stock in stocks]
    quotes = []
    for result in results:
        if not result.get("ok"):
            continue
        quote = result["quote"]
        quote["asset_type"] = "index" if quote["symbol"] == "KOSPI" else "stock"
        quotes.append(quote)
    return {
        "quotes": quotes,
        "errors": [result.get("error") for result in results if not result.get("ok")],
    }


def fetch_dashboard_quotes():
    results = [fetch_kospi(), *(fetch_stock(stock) for stock in TRACKED_STOCKS)]
    public_quotes = [result["quote"] for result in results if result.get("ok")]
    public_errors = [result.get("error") for result in results if not result.get("ok")]
    yahoo = fetch_yahoo_domestic_quotes()
    quotes = _merge_domestic_quotes(yahoo["quotes"], public_quotes)
    toss = {"quotes": [], "errors": []}
    if _toss_credentials_ready():
        toss = fetch_toss_domestic_quotes()
        quotes = _merge_domestic_quotes(toss["quotes"], quotes)
    available = {quote["symbol"] for quote in quotes}
    expected = {"KOSPI", *(stock["symbol"] for stock in TRACKED_STOCKS)}
    errors = [] if expected.issubset(available) else [*public_errors, *yahoo["errors"], *toss["errors"]]
    return {"quotes": quotes, "errors": [error for error in errors if error]}

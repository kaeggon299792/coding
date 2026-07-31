from dashboard_db import queries
from services import market_data


class FakeResponse:
    status_code = 200

    def json(self):
        return {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                "body": {
                    "items": {
                        "item": [
                            {
                                "basDt": "20260727",
                                "srtnCd": "034230",
                                "itmsNm": "파라다이스",
                                "mrktCtg": "KOSDAQ",
                                "clpr": "15100",
                                "vs": "-100",
                                "fltRt": "-0.66",
                            },
                            {
                                "basDt": "20260728",
                                "srtnCd": "034230",
                                "itmsNm": "파라다이스",
                                "mrktCtg": "KOSDAQ",
                                "clpr": "15420",
                                "vs": "320",
                                "fltRt": "2.12",
                                "mkp": "15100",
                                "hipr": "15550",
                                "lopr": "15020",
                                "trqu": "123456",
                                "mrktTotAmt": "901234567890",
                            },
                        ]
                    }
                },
            }
        }


class FakeYahooResponse:
    status_code = 200

    def json(self):
        return {
            "chart": {
                "result": [{
                    "meta": {
                        "currency": "HKD",
                        "regularMarketPrice": 20.5,
                        "chartPreviousClose": 20.0,
                        "regularMarketTime": 1785283200,
                        "regularMarketOpen": 20.1,
                        "regularMarketDayHigh": 20.8,
                        "regularMarketDayLow": 19.9,
                        "regularMarketVolume": 1234567,
                    },
                    "timestamp": [1785100000, 1785186400, 1785272800],
                    "indicators": {
                        "quote": [{"close": [19.8, 20.0, 20.5]}],
                        "adjclose": [{"adjclose": [19.8, 20.0, 20.5]}],
                    },
                }],
                "error": None,
            }
        }


class FakeTossCandleResponse:
    status_code = 200

    def json(self):
        return {"result": {"candles": [
            {"timestamp": "2026-07-30T00:00:00+09:00", "openPrice": "15000", "highPrice": "15300", "lowPrice": "14900", "closePrice": "15200", "volume": "1000", "currency": "KRW"},
            {"timestamp": "2026-07-31T00:00:00+09:00", "openPrice": "15200", "highPrice": "15700", "lowPrice": "15100", "closePrice": "15600", "volume": "2000", "currency": "KRW"},
        ]}}


def test_fetch_global_stock_without_api_key(monkeypatch):
    monkeypatch.setattr(
        "services.market_data.get_with_hard_timeout",
        lambda *args, **kwargs: FakeYahooResponse(),
    )
    result = market_data.fetch_global_stock(market_data.GLOBAL_STOCKS[0])
    assert result["ok"] is True
    assert result["quote"]["symbol"] == "1928.HK"
    assert result["quote"]["currency"] == "HKD"
    assert result["quote"]["change_value"] == 0.5
    assert result["quote"]["change_rate"] == 2.5
    assert len(result["quote"]["history"]) == 3


def test_fetch_stock_normalizes_market_fields(monkeypatch):
    monkeypatch.setattr("config.MARKET_DATA_API_KEY", "test-key")
    monkeypatch.setattr(
        "services.market_data.get_with_hard_timeout",
        lambda *args, **kwargs: FakeResponse(),
    )
    result = market_data.fetch_stock(market_data.TRACKED_STOCKS[0])
    quote = result["quote"]
    assert quote["symbol"] == "034230"
    assert quote["close_price"] == 15420
    assert quote["change_rate"] == 2.12
    assert quote["market_cap"] == 901234567890
    assert quote["history"] == [
        {"base_date": "20260727", "close_price": 15100},
        {"base_date": "20260728", "close_price": 15420},
    ]


def test_toss_quote_normalizes_latest_daily_candle(monkeypatch):
    monkeypatch.setattr(
        "services.market_data.get_with_hard_timeout",
        lambda *args, **kwargs: FakeTossCandleResponse(),
    )
    result = market_data._toss_quote(
        market_data.TRACKED_STOCKS[0], "token"
    )
    assert result["ok"] is True
    assert result["quote"]["base_date"] == "20260731"
    assert result["quote"]["close_price"] == 15600
    assert result["quote"]["change_value"] == 400
    assert result["quote"]["source"] == "토스증권 Open API"


def test_market_merge_prefers_newer_toss_but_keeps_market_cap():
    public = [{"symbol": "034230", "base_date": "20260730", "close_price": 15200, "market_cap": 900000, "source": "공공데이터"}]
    toss = [{"symbol": "034230", "base_date": "20260731", "close_price": 15600, "market_cap": None, "source": "토스증권 Open API"}]
    merged = market_data._merge_domestic_quotes(toss, public)[0]
    assert merged["base_date"] == "20260731"
    assert merged["close_price"] == 15600
    assert merged["market_cap"] == 900000


def test_market_quote_upsert_and_order(db_connection):
    for symbol, name in (("034230", "파라다이스"), ("KOSPI", "KOSPI")):
        queries.upsert_market_quote(
            db_connection,
            {
                "symbol": symbol,
                "name": name,
                "asset_type": "index" if symbol == "KOSPI" else "stock",
                "market": "KOSPI",
                "base_date": "20260728",
                "close_price": 100,
                "change_value": 1,
                "change_rate": 1.0,
                "market_cap": 1901234567890 if symbol == "034230" else None,
            },
        )
        queries.upsert_market_quote_history(
            db_connection,
            symbol,
            [
                {"base_date": "20260726", "close_price": 98},
                {"base_date": "20260727", "close_price": 99},
                {"base_date": "20260728", "close_price": 100},
            ],
        )
    rows = queries.list_market_quotes(db_connection)
    assert [row["symbol"] for row in rows] == ["KOSPI", "034230"]
    assert all(row["trend_count"] == 3 for row in rows)
    assert all(row["trend_points"].startswith("0.0,34.0") for row in rows)
    assert all(row["trend_area_points"].endswith("100,40") for row in rows)
    assert rows[1]["market_cap_label"] == "1조 9,012억원"


def test_global_quote_failure_keeps_last_successful_price(db_connection):
    quote = {
        "symbol": "MLCO",
        "name": "Melco Resorts & Entertainment",
        "asset_type": "global_stock",
        "market": "NASDAQ",
        "currency": "USD",
        "source": "Yahoo Finance",
        "base_date": "20260728",
        "close_price": 9.25,
        "change_value": -0.15,
        "change_rate": -1.6,
    }
    queries.upsert_market_quote(db_connection, quote)
    queries.mark_market_quote_failure(db_connection, "MLCO", "HTTP 429")
    row = next(
        item for item in queries.list_market_quotes(db_connection)
        if item["symbol"] == "MLCO"
    )
    assert row["close_price"] == 9.25
    assert row["fetch_status"] == "failed"
    assert row["fetch_error"] == "HTTP 429"


def test_global_quote_includes_latest_krw_estimate(db_connection):
    queries.upsert_economic_observation(db_connection, {
        "series_code": "FX_HKD", "observation_date": "20260731",
        "label": "홍콩 달러", "category": "exchange", "value": 180.5,
        "unit": "원", "source": "한국수출입은행",
    })
    queries.upsert_market_quote(db_connection, {
        "symbol": "1928.HK", "name": "Sands China", "asset_type": "global_stock",
        "market": "HKEX", "currency": "HKD", "source": "Yahoo Finance",
        "base_date": "20260731", "close_price": 20.0,
        "change_value": 0.5, "change_rate": 2.5,
    })
    row = next(item for item in queries.list_market_quotes(db_connection) if item["symbol"] == "1928.HK")
    assert row["krw_estimate"] == 3610
    assert row["krw_rate_date"] == "20260731"


def test_base_template_uses_system_theme_with_light_fallback():
    from pathlib import Path

    template = (Path(__file__).resolve().parents[1] / "templates" / "base.html").read_text(encoding="utf-8")
    assert 'matchMedia?.("(prefers-color-scheme: dark)")' in template
    assert '(systemDark ? "dark" : "light")' in template
    assert 'document.documentElement.dataset.theme || "light"' in template

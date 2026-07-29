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
                            }
                        ]
                    }
                },
            }
        }


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


def test_market_quote_upsert_and_order(db_connection):
    for symbol, name in (("034230", "파라다이스"), ("KOSPI", "KOSPI")):
        queries.upsert_market_quote(db_connection, {
            "symbol": symbol,
            "name": name,
            "asset_type": "index" if symbol == "KOSPI" else "stock",
            "market": "KOSPI",
            "base_date": "20260728",
            "close_price": 100,
            "change_value": 1,
            "change_rate": 1.0,
        })
    rows = queries.list_market_quotes(db_connection)
    assert [row["symbol"] for row in rows] == ["KOSPI", "034230"]

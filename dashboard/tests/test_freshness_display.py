from dashboard_db import queries, schema


def test_market_page_shows_separate_domestic_and_global_freshness(monkeypatch, tmp_path):
    import app as app_module

    db_path = tmp_path / "market.db"
    connection = schema.connect(db_path)
    queries.upsert_market_quote(connection, {
        "symbol": "034230",
        "name": "파라다이스",
        "asset_type": "stock",
        "market": "KOSPI",
        "base_date": "20260729",
        "close_price": 12000,
        "change_value": 100,
        "change_rate": 0.84,
        "open_price": 11900,
        "high_price": 12100,
        "low_price": 11800,
        "volume": 1000,
        "market_cap": 1_200_000_000_000,
        "currency": "KRW",
        "source": "테스트",
    })
    queries.upsert_market_quote(connection, {
        "symbol": "MLCO",
        "name": "Melco Resorts & Entertainment",
        "asset_type": "global_stock",
        "market": "NASDAQ",
        "base_date": "20260731",
        "close_price": 9.25,
        "change_value": 0.15,
        "change_rate": 1.65,
        "open_price": 9.10,
        "high_price": 9.30,
        "low_price": 9.00,
        "volume": 2000,
        "market_cap": None,
        "currency": "USD",
        "source": "Yahoo Finance",
    })
    connection.execute(
        "UPDATE market_quotes SET fetched_at=? WHERE symbol='034230'",
        ("2026-07-30T08:30:00+09:00",),
    )
    connection.execute(
        "UPDATE market_quotes SET fetched_at=? WHERE symbol='MLCO'",
        ("2026-07-31T12:36:00+09:00",),
    )
    connection.commit()
    connection.close()

    monkeypatch.setattr(app_module, "dashboard_db", lambda: schema.connect(db_path))
    monkeypatch.setattr(app_module.queries, "global_market_quotes_need_refresh", lambda *_args, **_kwargs: False)

    app_module.app.testing = True
    response = app_module.app.test_client().get("/performance/markets")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "국내 최종 확인" in body
    assert "해외 최종 확인" in body
    assert "2026-07-30 08:30" in body
    assert "2026-07-31 12:36" in body
    assert "국내 기준일" in body
    assert "해외 기준일" in body


def test_economy_page_shows_oil_and_exchange_freshness_separately(monkeypatch, tmp_path):
    import app as app_module

    db_path = tmp_path / "economy.db"
    connection = schema.connect(db_path)
    queries.upsert_economic_observation(connection, {
        "series_code": "OIL_B027",
        "observation_date": "20260729",
        "label": "보통휘발유",
        "category": "oil",
        "value": 1662.12,
        "unit": "원/L",
        "source": "한국석유공사 오피넷",
    })
    queries.upsert_economic_observation(connection, {
        "series_code": "FX_USD",
        "observation_date": "20260730",
        "label": "미국 달러",
        "category": "exchange",
        "value": 1388.50,
        "unit": "원",
        "source": "한국수출입은행",
    })
    connection.execute(
        "UPDATE economic_series SET fetched_at=?, changed_at=? WHERE series_code='OIL_B027'",
        ("2026-07-29T18:22:00+09:00", "2026-07-29T18:22:00+09:00"),
    )
    connection.execute(
        "UPDATE economic_series SET fetched_at=?, changed_at=? WHERE series_code='FX_USD'",
        ("2026-07-30T09:10:00+09:00", "2026-07-30T09:10:00+09:00"),
    )
    connection.commit()
    connection.close()

    monkeypatch.setattr(app_module, "dashboard_db", lambda: schema.connect(db_path))

    app_module.app.testing = True
    response = app_module.app.test_client().get("/performance/economy")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "유가 최종 확인" in body
    assert "유가 최종 변경" in body
    assert "환율 최종 확인" in body
    assert "환율 최종 변경" in body
    assert "2026-07-29 18:22" in body
    assert "2026-07-30 09:10" in body

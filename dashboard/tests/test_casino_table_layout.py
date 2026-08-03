from pathlib import Path

import pytest


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(tmp_path / "casino_table.db"))
    import app as app_module

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def test_revenue_table_has_aligned_columns_and_krw_notes(client):
    response = client.get("/performance/casino-industry/revenue")

    assert response.status_code == 200
    assert b"<colgroup>" in response.data
    assert b"casino-money-cell" in response.data
    assert b"casino-krw-note" in response.data
    assert "약 2.4조원".encode() in response.data
    assert "1달러≈1,500원".encode() in response.data


def test_fund_table_has_header_aligned_columns(client):
    response = client.get("/performance/casino-industry/fund")

    assert response.status_code == 200
    assert b"casino-fund-table" in response.data
    assert b'<col style="width:190px">' in response.data
    assert response.data.count(b'<col style="width:90px">') == 10


def test_casino_overview_grid_keeps_summary_inside_page():
    css = (Path(__file__).parents[1] / "static" / "css" / "dashboard.css").read_text(
        encoding="utf-8"
    )

    assert "grid-template-columns:minmax(0,1.2fr) minmax(420px,.8fr)" in css
    assert ".casino-industry-summary{display:grid;min-width:0" in css
    base = (Path(__file__).parents[1] / "templates" / "base.html").read_text(
        encoding="utf-8"
    )
    assert "v=20260801-casino-layout" in base

import sqlite3

from dashboard_db import queries


def test_tourism_ytd_comparison_uses_same_month_range_for_both_years():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE tourism_visitor_stats (
            ym TEXT, nat_label TEXT, visitor_count INTEGER, fetched_at TEXT,
            UNIQUE(ym, nat_label)
        )
        """
    )
    periods = [(f"2025{month:02d}", month) for month in range(1, 13)]
    periods += [("202601", 3), ("202602", 4)]
    for ym, multiplier in periods:
        for label, base in zip(queries.TOURISM_CATEGORIES, (100, 80, 40, 20, 60)):
            connection.execute(
                "INSERT INTO tourism_visitor_stats VALUES (?, ?, ?, ?)",
                (ym, label, base * multiplier, "2026-07-29T12:00:00+09:00"),
            )

    result = queries.get_tourism_ytd_comparison(connection)

    assert result["this_year"] == 2026
    assert result["last_year"] == 2025
    assert result["period_label"] == "1~2월"
    assert result["complete"] is True
    china = result["categories"][0]
    assert china["last_value"] == 300
    assert china["this_value"] == 700
    assert china["difference"] == 400
    assert china["change_rate"] == 133.3
    assert china["projected_total"] == 19450
    assert china["forecast_points"]


def test_tourism_ytd_comparison_returns_none_without_cache():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE tourism_visitor_stats (
            ym TEXT, nat_label TEXT, visitor_count INTEGER, fetched_at TEXT
        )
        """
    )
    assert queries.get_tourism_ytd_comparison(connection) is None

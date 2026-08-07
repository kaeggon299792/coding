import json

from dashboard_db import queries


def test_admin_dashboard_counts_todays_security_events(db_connection):
    db_connection.executemany(
        """
        INSERT INTO security_audit_log(
            username, action, success, created_at
        ) VALUES (?, ?, ?, ?)
        """,
        (
            ("anonymous", "SECURITY_RATE_LIMIT", 0, "2026-08-06T09:10:00+09:00"),
            ("anonymous", "SECURITY_THRESHOLD_ALERT", 0, "2026-08-06T09:11:00+09:00"),
            ("anonymous", "PAGE_VIEW", 1, "2026-08-06T09:12:00+09:00"),
            ("anonymous", "SECURITY_RATE_LIMIT", 0, "2026-08-05T23:59:00+09:00"),
        ),
    )
    db_connection.commit()

    metrics = queries.get_admin_dashboard_metrics(db_connection, "2026-08-06")

    assert metrics["security_events"] == 2


def test_admin_dashboard_counts_unique_visitors_by_legacy_domain(db_connection):
    rows = [
        ("1.1.1.1", "casino.shingoon.me"),
        ("1.1.1.1", "casino.shingoon.me"),
        ("2.2.2.2", "www.casino.shingoon.me"),
        ("1.1.1.1", "dashboard.shingoon.me"),
        ("3.3.3.3", "www.casinoin.kr"),
    ]
    db_connection.executemany(
        """INSERT INTO security_audit_log(
               username, ip_address, action, resource_type, resource_id,
               success, detail_json, created_at
           ) VALUES ('anonymous', ?, 'PAGE_VIEW', 'endpoint', '/', 1, ?, ?)""",
        [
            (ip, json.dumps({"host": host}), "2026-08-06T10:00:00+09:00")
            for ip, host in rows
        ],
    )
    db_connection.commit()

    metrics = queries.get_admin_dashboard_metrics(db_connection, "2026-08-06")

    assert metrics["casino_domain_visitors"] == 2
    assert metrics["dashboard_domain_visitors"] == 1

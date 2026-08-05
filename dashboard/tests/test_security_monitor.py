from flask import Response

from dashboard_db import schema
from services import security_monitor


def test_path_probe_alerts_only_at_threshold(monkeypatch, tmp_path):
    import app as app_module

    db = schema.connect(str(tmp_path / "security-monitor.db"))
    sent = []
    monkeypatch.setattr(security_monitor.telegram_alert, "send_alert", lambda text, **kwargs: sent.append(text) or True)
    app_module.app.config["TESTING"] = False

    for _ in range(3):
        with app_module.app.test_request_context(
            "/.env", headers={"CF-Connecting-IP": "203.0.113.9"}
        ):
            response = Response(status=404)
            security_monitor.inspect_response(db, response)
            db.commit()

    events = db.execute(
        "SELECT action,ip_address FROM security_audit_log ORDER BY id"
    ).fetchall()
    db.close()
    assert [row["action"] for row in events].count("SECURITY_PATH_PROBE") == 3
    assert [row["action"] for row in events].count("SECURITY_THRESHOLD_ALERT") == 1
    assert all(row["ip_address"] == "203.0.113.9" for row in events)
    assert len(sent) == 1


def test_normal_response_is_not_a_security_event():
    from flask import g
    import app as app_module

    with app_module.app.test_request_context("/news"):
        g.csrf_validation_failed = False
        assert security_monitor.should_inspect(Response(status=200)) is False

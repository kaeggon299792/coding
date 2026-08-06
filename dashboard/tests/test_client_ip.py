from flask import Flask

from services.client_ip import get_client_ip, normalize_ip


def _resolved(headers=None, remote_addr="10.0.0.5"):
    app = Flask(__name__)
    with app.test_request_context(
        "/", headers=headers or {}, environ_base={"REMOTE_ADDR": remote_addr}
    ):
        return get_client_ip()


def test_cloudflare_ipv4_is_used_only_behind_cloudflare():
    assert _resolved({
        "X-Real-IP": "172.68.10.20",
        "CF-Connecting-IP": "203.0.113.44",
    }) == "203.0.113.44"


def test_cloudflare_ipv6_is_normalized():
    assert _resolved({
        "X-Real-IP": "2606:4700::100",
        "CF-Connecting-IP": "2001:db8:0:0:0:0:0:8",
    }) == "2001:db8::8"


def test_missing_headers_fall_back_to_remote_addr():
    assert _resolved(remote_addr="198.51.100.7") == "198.51.100.7"


def test_empty_invalid_and_multiple_values_are_rejected():
    assert normalize_ip("") == ""
    assert normalize_ip("not-an-ip") == ""
    assert normalize_ip("203.0.113.1, 198.51.100.1") == ""


def test_spoofed_cloudflare_header_is_ignored_on_direct_request():
    assert _resolved({
        "X-Real-IP": "198.51.100.8",
        "CF-Connecting-IP": "203.0.113.99",
        "X-Forwarded-For": "192.0.2.10",
    }) == "198.51.100.8"


def test_pythonanywhere_direct_request_uses_platform_real_ip():
    assert _resolved({"X-Real-IP": "2001:db8::12"}) == "2001:db8::12"


def test_two_visitors_behind_same_cloudflare_edge_remain_distinct():
    edge = "162.158.1.9"
    first = _resolved({"X-Real-IP": edge, "CF-Connecting-IP": "203.0.113.10"})
    second = _resolved({"X-Real-IP": edge, "CF-Connecting-IP": "203.0.113.11"})
    assert first != second


def test_cloudflare_pseudo_ipv4_prefers_preserved_ipv6():
    assert _resolved({
        "X-Real-IP": "104.23.1.5",
        "CF-Connecting-IP": "240.1.2.3",
        "CF-Connecting-IPv6": "2001:db8::1234",
    }) == "2001:db8::1234"


def test_ipv6_is_not_truncated_in_audit_storage(db_connection):
    from services import security_audit

    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context(
        "/",
        headers={
            "X-Real-IP": "172.64.0.10",
            "CF-Connecting-IP": "2001:db8:1234:5678:90ab:cdef:1234:5678",
        },
    ):
        security_audit.log_event(db_connection, "IPV6_STORAGE_TEST")
        db_connection.commit()
    stored = db_connection.execute(
        "SELECT ip_address FROM security_audit_log WHERE action='IPV6_STORAGE_TEST'"
    ).fetchone()[0]
    assert stored == "2001:db8:1234:5678:90ab:cdef:1234:5678"

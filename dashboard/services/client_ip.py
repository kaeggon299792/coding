"""Resolve and normalize request IP addresses behind PythonAnywhere and Cloudflare."""

from ipaddress import ip_address, ip_network

from flask import has_request_context, request


_CLOUDFLARE_NETWORKS = tuple(
    ip_network(value)
    for value in (
        "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
        "104.16.0.0/13", "104.24.0.0/14", "108.162.192.0/18",
        "131.0.72.0/22", "141.101.64.0/18", "162.158.0.0/15",
        "172.64.0.0/13", "173.245.48.0/20", "188.114.96.0/20",
        "190.93.240.0/20", "197.234.240.0/22", "198.41.128.0/17",
        "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32",
        "2405:b500::/32", "2405:8100::/32", "2a06:98c0::/29",
        "2c0f:f248::/32",
    )
)
_PSEUDO_IPV4_NETWORK = ip_network("240.0.0.0/4")


def normalize_ip(value):
    """Return a canonical single IPv4/IPv6 address, or an empty string."""
    text = str(value or "").strip()
    if not text or len(text) > 128 or "," in text:
        return ""
    try:
        return ip_address(text).compressed
    except ValueError:
        return ""


def is_cloudflare_ip(value):
    normalized = normalize_ip(value)
    if not normalized:
        return False
    parsed = ip_address(normalized)
    return any(parsed in network for network in _CLOUDFLARE_NETWORKS)


def get_client_ip(default="unknown"):
    """Return the client IP without trusting caller-supplied forwarding headers.

    PythonAnywhere guarantees ``X-Real-IP`` as the address received by its load
    balancer.  Only when that immediate address belongs to Cloudflare do we
    accept Cloudflare's original-client header.  ``X-Forwarded-For`` is never
    used because its leading values can be supplied by the caller.
    """
    if not has_request_context():
        return default

    pythonanywhere_peer = normalize_ip(request.headers.get("X-Real-IP"))
    if pythonanywhere_peer:
        if is_cloudflare_ip(pythonanywhere_peer):
            cloudflare_client = normalize_ip(request.headers.get("CF-Connecting-IP"))
            if cloudflare_client:
                parsed = ip_address(cloudflare_client)
                if parsed.version == 4 and parsed in _PSEUDO_IPV4_NETWORK:
                    original_ipv6 = normalize_ip(
                        request.headers.get("CF-Connecting-IPv6")
                    )
                    if original_ipv6 and ip_address(original_ipv6).version == 6:
                        return original_ipv6
                return cloudflare_client
        return pythonanywhere_peer

    return normalize_ip(request.remote_addr) or default

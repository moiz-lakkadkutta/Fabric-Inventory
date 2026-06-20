"""T3 security tests — rate-limit client-IP extraction (DOS-06).

DOS-06: the existing limiter trusted the LEFTMOST X-Forwarded-For entry,
which an attacker behind a reverse proxy can freely spoof by injecting a
fake header before the legitimate proxy appends the actual client IP.

The fix: use the RIGHTMOST XFF entry (added by our trusted Caddy proxy),
which cannot be forged by the attacker.

These tests are pure-Python: they call ``_client_ip`` directly with
constructed Starlette ``Request`` objects — no DB, no Redis, no network.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.types import Scope


def _make_request(headers: dict[str, str], client_host: str = "127.0.0.1") -> Request:
    """Build a minimal Starlette Request from raw header dict + client tuple."""
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "query_string": b"",
        "headers": raw_headers,
        "client": (client_host, 12345),
        "server": ("127.0.0.1", 8000),
        "scheme": "http",
        "root_path": "",
    }
    return Request(scope)


# ──────────────────────────────────────────────────────────────────────
# DOS-06 — Rightmost XFF, not leftmost
# ──────────────────────────────────────────────────────────────────────


def test_client_ip_uses_rightmost_xff_entry() -> None:
    """DOS-06: an attacker can inject a fake IP as the leftmost XFF entry.
    Our proxy (Caddy) appends the actual peer IP as the RIGHTMOST entry.
    _client_ip must return the rightmost entry, not the attacker-controlled
    leftmost one.
    """
    from app.middleware.rate_limit import _client_ip

    # XFF: attacker-supplied leftmost entry, real IP appended by Caddy.
    request = _make_request({"X-Forwarded-For": "1.2.3.4, 10.0.0.1"})
    ip = _client_ip(request)

    # Must be the rightmost (Caddy-added) IP, NOT the attacker-supplied leftmost.
    assert ip == "10.0.0.1", (
        f"_client_ip returned {ip!r} (leftmost) instead of '10.0.0.1' (rightmost). "
        "DOS-06: use rightmost XFF — the entry added by the trusted proxy."
    )
    assert ip != "1.2.3.4", "Returned attacker-spoofable leftmost XFF entry!"


def test_client_ip_strips_whitespace_from_rightmost() -> None:
    """Entries in XFF may have leading/trailing whitespace; strip it."""
    from app.middleware.rate_limit import _client_ip

    request = _make_request({"X-Forwarded-For": "5.5.5.5 , 192.168.1.100 "})
    ip = _client_ip(request)
    assert ip == "192.168.1.100", f"Expected stripped rightmost IP, got {ip!r}"


def test_client_ip_single_xff_entry() -> None:
    """When XFF has only one entry (e.g. no chained proxies), that IS the rightmost."""
    from app.middleware.rate_limit import _client_ip

    request = _make_request({"X-Forwarded-For": "203.0.113.5"})
    ip = _client_ip(request)
    assert ip == "203.0.113.5"


def test_client_ip_falls_back_to_socket_when_no_xff() -> None:
    """No XFF header → use the TCP socket peer address."""
    from app.middleware.rate_limit import _client_ip

    request = _make_request({}, client_host="192.0.2.1")
    ip = _client_ip(request)
    assert ip == "192.0.2.1"


def test_client_ip_three_hop_chain_returns_rightmost() -> None:
    """A three-hop XFF chain (attacker → intermediate → our-proxy): rightmost wins."""
    from app.middleware.rate_limit import _client_ip

    request = _make_request({"X-Forwarded-For": "evil.attacker.com, 10.1.2.3, 10.0.0.99"})
    ip = _client_ip(request)
    # The rightmost is what our edge proxy appended.
    assert ip == "10.0.0.99"
    assert "evil.attacker.com" not in ip

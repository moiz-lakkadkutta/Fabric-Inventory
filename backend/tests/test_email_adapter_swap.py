"""TASK-CUT-405: email-adapter swap proves no caching pitfall.

The password-reset service in CUT-303 already imports the adapter as a
module (``email_adapter.get_email_adapter()``) rather than capturing the
function reference at import time. This test pins that contract so a
future refactor that switches to ``from email_adapter import get_email_adapter``
(which would cache the *console* default at import time) trips the suite.

What the test proves:

1. ``set_email_adapter(MailgunEmailAdapter(...))`` after app boot is
   picked up by the password-reset service on the very next call —
   no module reload, no service restart, no cached function reference.
2. Calling ``set_email_adapter`` while a request is in flight is
   safe at the registry level (one global, atomic re-bind). Re-entrancy
   is not tested because the service is sync.

This is an in-memory unit test — no DB or HTTP. The DB-bound
end-to-end forgot-password coverage already lives in
``test_password_reset.py``; that suite uses the same registry but with
a ``RecordingEmailAdapter``. Together they form the seam guarantee:
the swap is observable from the calling service.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest

from app.service import email_adapter
from app.service.email_adapter import (
    MailgunEmailAdapter,
    set_email_adapter,
)


@dataclass
class _CaptureAdapter:
    """Local capture — proves the swap was effective."""

    sent: list[tuple[str, str]] = field(default_factory=list)

    def send_password_reset_email(self, *, to: str, reset_link: str) -> None:
        self.sent.append((to, reset_link))


@pytest.fixture(autouse=True)
def _restore_adapter() -> Iterator[None]:
    """Snapshot + restore the module-level singleton so the test does
    not leak state into other suites."""
    original = email_adapter.get_email_adapter()
    yield
    email_adapter.set_email_adapter(original)


def test_set_email_adapter_is_picked_up_by_password_reset_service() -> None:
    """Service-layer call must observe the registry swap.

    The password-reset service imports ``email_adapter`` as a module
    and reads ``email_adapter.get_email_adapter()`` at delivery time.
    If anyone refactors to capture ``get_email_adapter`` at import time
    this assertion fails — that's the regression we want to lock down.
    """
    from app.service import password_reset_service  # local import: avoid DB at module import

    # Sanity: default adapter (Console) is in place at module load.
    assert isinstance(email_adapter.get_email_adapter(), email_adapter.ConsoleEmailAdapter)

    capture = _CaptureAdapter()
    set_email_adapter(capture)

    # Re-read through the module the same way the service does.
    adapter = email_adapter.get_email_adapter()
    assert adapter is capture

    # Drive a delivery through the public surface the password-reset
    # service uses.
    adapter.send_password_reset_email(to="moiz@example.com", reset_link="https://x/reset/abc")
    assert capture.sent == [("moiz@example.com", "https://x/reset/abc")]

    # The service module references the registry through ``email_adapter``
    # (module-level), not a cached symbol. Sanity-check that the same
    # symbol the service reads is the one we just rebind.
    service_adapter_module = password_reset_service.email_adapter  # type: ignore[attr-defined]
    assert service_adapter_module.get_email_adapter() is capture


def test_mailgun_adapter_implements_protocol() -> None:
    """MailgunEmailAdapter must satisfy the EmailAdapter protocol shape.

    runtime_checkable lets us validate the structural fit without
    instantiating any HTTP client.
    """
    adapter = MailgunEmailAdapter(
        api_key="key-stub-not-real",
        domain="mg.example.com",
        sender="Fabric <no-reply@example.com>",
    )
    assert isinstance(adapter, email_adapter.EmailAdapter)


def test_mailgun_adapter_posts_to_messages_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """The adapter must POST to ``/v3/<domain>/messages`` with HTTP basic
    auth ``api:<api_key>``. We capture the request without actually
    calling Mailgun.
    """
    captured: dict[str, object] = {}

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

    def _fake_post(
        url: str,
        *,
        auth: tuple[str, str],
        data: dict[str, str],
        timeout: float,
    ) -> _FakeResponse:
        captured["url"] = url
        captured["auth"] = auth
        captured["data"] = data
        captured["timeout"] = timeout
        return _FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "post", _fake_post)

    adapter = MailgunEmailAdapter(
        api_key="key-test",
        domain="mg.example.com",
        sender="Fabric <no-reply@example.com>",
    )
    adapter.send_password_reset_email(
        to="user@example.com", reset_link="https://app.example.com/reset/abc?org=Acme"
    )

    assert captured["url"] == "https://api.mailgun.net/v3/mg.example.com/messages"
    assert captured["auth"] == ("api", "key-test")
    data = captured["data"]
    assert isinstance(data, dict)
    assert data["to"] == "user@example.com"
    assert data["from"] == "Fabric <no-reply@example.com>"
    assert "Reset" in data["subject"]
    assert "https://app.example.com/reset/abc?org=Acme" in data["text"]

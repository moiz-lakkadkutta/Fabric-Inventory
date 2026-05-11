"""Email adapter — Protocol + dev console-log impl + Mailgun prod impl + test recorder.

Purpose (CUT-303 + CUT-405): the forgot-password flow needs to deliver
a ``/reset/<token>`` link to a user. In dev we print to stdout so
``tail -f /tmp/uvicorn-*.log`` shows it; that aligns with the wave-4
demo doc. In production (CUT-405) ``MailgunEmailAdapter`` POSTs to
``https://api.mailgun.net/v3/<domain>/messages`` with HTTP basic auth.

Design notes:
  - ``EmailAdapter`` is a Protocol with one method:
    ``send_password_reset_email``. Future emails (signup welcome,
    MFA-reset, invite) will add methods here, but keeping the surface
    narrow for now matches the YAGNI principle — we can broaden the
    contract when the second caller actually exists.
  - A module-level singleton (``_adapter``) is set at app boot via
    ``set_email_adapter(...)`` and read by services via
    ``get_email_adapter()``. This is the seam tests use to swap in a
    ``RecordingEmailAdapter`` and assert against what was "sent" —
    no monkeypatching of stdout required. Callers MUST import the
    module (``from app.service import email_adapter``) and read via
    ``email_adapter.get_email_adapter()`` so registry swaps after app
    boot are observed; importing ``get_email_adapter`` as a symbol
    caches the *console* default at import time and silently defeats
    the swap. ``test_email_adapter_swap.py`` pins this contract.
  - The console-log impl deliberately uses ``print()`` rather than
    structlog: stdout is the demo target, and structlog's JSON
    formatter would bury the link. The token itself is logged because
    this is the dev adapter — in prod, swapping to the real adapter
    means the raw token never touches a log.
  - Mailgun was picked over Postmark because the flex plan ($35/mo for
    50k emails) is the cheapest credible option for an Indian SaaS at
    this stage. Postmark is the documented fallback in
    ``docs/retros/task-CUT-405.md`` — the swap is a one-class change
    (replace ``MailgunEmailAdapter`` with ``PostmarkEmailAdapter``;
    same Protocol).

This module has no DB / FastAPI deps so it can be imported from
``service/password_reset_service.py`` without a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@runtime_checkable
class EmailAdapter(Protocol):
    """Pluggable email delivery surface.

    The reset link is built by the caller (it knows the FRONTEND_URL +
    raw token); the adapter just delivers the message. Returns nothing
    because send-and-forget is the contract for now — the prod adapter
    will gain delivery-status hooks later.
    """

    def send_password_reset_email(self, *, to: str, reset_link: str) -> None: ...


class ConsoleEmailAdapter:
    """Dev adapter — prints the reset link to stdout.

    Aligned with the wave-4 demo doc's
    ``tail -f /tmp/uvicorn-*.log`` workflow. The banner is verbose so
    the link is easy to grep / eyeball amid request log noise.
    """

    def send_password_reset_email(self, *, to: str, reset_link: str) -> None:
        # Intentional print — see module docstring for the rationale.
        print(
            "\n"
            "============================================================\n"
            f"  [email_adapter] PASSWORD RESET LINK for {to}\n"
            f"  {reset_link}\n"
            "  (Dev console adapter — link valid for 30 minutes.)\n"
            "============================================================",
            flush=True,
        )


@dataclass(frozen=True)
class MailgunEmailAdapter:
    """Production adapter — POSTs to the Mailgun Messages API.

    Constructor args:
      - ``api_key``: Mailgun private API key (``key-...``). Loaded from
        ``MAILGUN_API_KEY`` env var on app boot.
      - ``domain``: Mailgun sending domain, e.g. ``mg.taana.in``. SPF +
        DKIM records for this domain MUST be in place; see the DNS
        section of ``docs/ops/deployment-runbook.md``.
      - ``sender``: RFC-5322 ``From`` value, e.g.
        ``"Fabric ERP <no-reply@mg.taana.in>"``.
      - ``api_base``: defaults to the US Mailgun region. EU customers
        override this to ``https://api.eu.mailgun.net``.

    The adapter calls ``httpx.post`` synchronously because the
    password-reset service is sync (Session). ``timeout=10`` matches
    Mailgun's documented p99 latency. A non-2xx response raises
    ``httpx.HTTPStatusError`` — the password-reset service is expected
    to swallow it (we already silently no-op on unknown email; a
    Mailgun outage SHOULD NOT leak whether the email existed). Logging
    a structlog warning on failure is the right call but is deferred
    to the first time it actually misfires.
    """

    api_key: str
    domain: str
    sender: str
    api_base: str = "https://api.mailgun.net"

    def send_password_reset_email(self, *, to: str, reset_link: str) -> None:
        # Local import: httpx is in the dev group today; the prod
        # Docker image installs it via the ``fastapi[standard]`` extra
        # (httpx is a transitive dep of starlette.testclient + fastapi
        # CLI). Keeping the import local avoids cost at module load
        # for the ConsoleEmailAdapter path the dev box hits.
        import httpx

        url = f"{self.api_base.rstrip('/')}/v3/{self.domain}/messages"
        body_text = (
            "Hi,\n\n"
            "Someone (hopefully you) requested a password reset on Fabric ERP.\n"
            "Open the link below to set a new password — it expires in 30 minutes.\n\n"
            f"{reset_link}\n\n"
            "If you did not request this, you can safely ignore this email; "
            "your password is unchanged.\n\n"
            "— Fabric ERP"
        )
        response = httpx.post(
            url,
            auth=("api", self.api_key),
            data={
                "from": self.sender,
                "to": to,
                "subject": "Reset your Fabric ERP password",
                "text": body_text,
            },
            timeout=10.0,
        )
        response.raise_for_status()


@dataclass
class _Delivery:
    """Single recorded delivery — used by tests."""

    to: str
    reset_link: str


@dataclass
class RecordingEmailAdapter:
    """Test-only adapter that captures deliveries in a list.

    Lives here (alongside the production adapter) rather than in the
    test tree so service-layer unit tests outside ``backend/tests/``
    can use it too. The class is plain data; no I/O.
    """

    sent: list[_Delivery] = field(default_factory=list)

    def send_password_reset_email(self, *, to: str, reset_link: str) -> None:
        self.sent.append(_Delivery(to=to, reset_link=reset_link))


# Module-level singleton. Default to the dev/console adapter so any
# unwrapped import works; tests swap it via set_email_adapter().
_adapter: EmailAdapter = ConsoleEmailAdapter()


def get_email_adapter() -> EmailAdapter:
    return _adapter


def set_email_adapter(adapter: EmailAdapter) -> None:
    """Wire in a different adapter — used by tests and (eventually) the
    Wave-5 swap to the real provider at app boot."""
    global _adapter
    _adapter = adapter


__all__ = [
    "ConsoleEmailAdapter",
    "EmailAdapter",
    "MailgunEmailAdapter",
    "RecordingEmailAdapter",
    "get_email_adapter",
    "set_email_adapter",
]

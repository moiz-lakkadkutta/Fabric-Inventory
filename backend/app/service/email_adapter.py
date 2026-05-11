"""Email adapter — Protocol + dev console-log impl + test recorder.

Purpose (CUT-303): the forgot-password flow needs to deliver a
``/reset/<token>`` link to a user. In production this is a real
provider (Mailgun, Postmark, SES — landing in Wave 5 as CUT-405). In
dev we just want the link printed to stdout so ``tail -f /tmp/uvicorn-*.log``
shows it; that aligns with the wave-4 demo doc.

Design notes:
  - ``EmailAdapter`` is a Protocol with one method: ``send_password_reset_email``.
    Future emails (signup welcome, MFA-reset, invite) will add methods
    here, but keeping the surface narrow for now matches the YAGNI
    principle — we can broaden the contract when the second caller
    actually exists.
  - A module-level singleton (``_adapter``) is set at app boot via
    ``set_email_adapter(...)`` and read by services via
    ``get_email_adapter()``. This is the seam tests use to swap in a
    ``RecordingEmailAdapter`` and assert against what was "sent" —
    no monkeypatching of stdout required.
  - The console-log impl deliberately uses ``print()`` rather than
    structlog: stdout is the demo target, and structlog's JSON
    formatter would bury the link. The token itself is logged because
    this is the dev adapter — in prod, swapping to the real adapter
    means the raw token never touches a log.

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
    "RecordingEmailAdapter",
    "get_email_adapter",
    "set_email_adapter",
]

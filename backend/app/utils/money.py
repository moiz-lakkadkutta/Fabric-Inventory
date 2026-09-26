"""Money magnitude guards — #207.

A single business ceiling for every derived money amount (line products,
document totals, GST amounts) so a value that individually passes its
per-field cap but overflows once multiplied/summed is rejected with a
clean 422 *before* it ever reaches a ``NUMERIC(18,2)`` column and 500s.

The DB columns (``NUMERIC(18,2)`` for money, ``NUMERIC(15,4)`` for qty)
remain the authoritative hard limits; ``MAX_MONEY`` is a deliberately
lower, business-sane ceiling. Raising it is a one-line change here plus
a test update.

PENDING MOIZ SIGN-OFF: ``MAX_MONEY`` = ₹1e9 (₹100 crore) per document /
per line is a money-policy call. It is consistent with the existing
BL-02 ₹1e9 per-field caps on invoice lines. A legitimate customer that
needs a higher ceiling changes only this constant.
"""

from __future__ import annotations

from decimal import Decimal

from app.exceptions import AppValidationError

# ₹1e9 business ceiling for any single derived amount. Well within the
# NUMERIC(18,2) hard limit (9,999,999,999,999,999.99).
MAX_MONEY = Decimal("1000000000.00")


def ensure_money_in_range(value: Decimal, *, field: str) -> Decimal:
    """Return ``value`` unchanged if ``abs(value) <= MAX_MONEY``.

    Otherwise raise :class:`AppValidationError` (HTTP 422) with a
    per-field message under ``field_errors[field]`` so the frontend can
    surface it on the offending line/total rather than a generic banner.
    """
    if abs(value) > MAX_MONEY:
        msg = (
            f"{field} of ₹{value} exceeds the supported maximum of "
            f"₹{MAX_MONEY}. Split the document or reduce the amount."
        )
        raise AppValidationError(msg, field_errors={field: [msg]})
    return value

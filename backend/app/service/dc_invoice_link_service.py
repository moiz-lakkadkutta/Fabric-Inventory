"""Delivery challan -> sales invoice linkage (DEBT-02 + #209).

An invoice may bill exactly one delivery challan (DC), and a DC may be billed
by at most one LIVE invoice. "Live" means not soft-deleted and not
CANCELLED / DISCARDED — a DRAFT counts, so a DC can't sit on two drafts. When
the invoice is cancelled the link is released and the DC can be billed again.

Why the link matters: ``issue_dc`` already relieved the stock. A DC-linked
invoice must therefore NOT relieve stock again at finalize; it takes its COGS
cost basis from the DC's outbound stock movements instead
(``sales_service._post_cogs_for_dc_invoice``). Two live invoices on one DC
would post COGS twice for one physical dispatch.

Concurrency (#209): every link-time and finalize-time check runs after
``lock_dc_for_invoicing`` takes ``SELECT ... FOR UPDATE`` on the DC row, so
overlapping creates on one DC serialize and the loser's re-check sees the
winner. The partial unique index ``uq_sales_invoice_delivery_challan_live``
(migration ``209_dc_invoice_link``) is the DB backstop; its violation is
translated to the same 422 by ``translate_link_integrity_error``.

Lock order (deadlock avoidance): invoice row (finalize only) -> DC row ->
firm row (document / voucher numbering). Callers take the DC lock BEFORE
anything that locks the firm row.

Line rule (one invoice <-> one DC, no partial / consolidated billing yet): the
invoice's stockable (non-SERVICE) lines must bill exactly the DC's stockable
items, with the same total quantity per item. Prices may differ from the DC
(the DC price is indicative). SERVICE lines (freight, packing) may be added
freely; SERVICE lines on the DC are ignored (they never moved stock). The
equal-quantity rule keeps COGS — which is taken from the WHOLE DC — matched to
the revenue billed.

GATED — COGS / schema change, PENDING MOIZ SIGN-OFF.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.exceptions import AppValidationError
from app.models import DeliveryChallan, Item, SalesInvoice
from app.models.masters import ItemType
from app.models.sales import DCStatus, InvoiceLifecycleStatus

# DC states in which goods have physically left and the DC can be billed.
INVOICEABLE_DC_STATUSES = frozenset({DCStatus.ISSUED.value, DCStatus.ACKNOWLEDGED.value})

# Invoice states that no longer hold their DC (mirrors the index predicate).
RELEASED_INVOICE_STATUSES = frozenset(
    {InvoiceLifecycleStatus.CANCELLED, InvoiceLifecycleStatus.DISCARDED}
)

LINK_UNIQUE_INDEX = "uq_sales_invoice_delivery_challan_live"


def _dc_label(dc: DeliveryChallan) -> str:
    return f"{dc.series}/{dc.number}"


def lock_dc_for_invoicing(
    session: Session, *, org_id: uuid.UUID, dc_id: uuid.UUID
) -> DeliveryChallan | None:
    """``SELECT ... FOR UPDATE`` the (non-deleted) DC row and refresh it.

    ``populate_existing`` makes a waiter that wakes after another transaction
    commits see the fresh row, not a stale identity-map copy.
    """
    return session.execute(
        select(DeliveryChallan)
        .options(selectinload(DeliveryChallan.lines))
        .where(
            DeliveryChallan.delivery_challan_id == dc_id,
            DeliveryChallan.org_id == org_id,
            DeliveryChallan.deleted_at.is_(None),
        )
        .with_for_update(of=DeliveryChallan)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def find_live_invoice_on_dc(
    session: Session,
    *,
    org_id: uuid.UUID,
    dc_id: uuid.UUID,
    exclude_invoice_id: uuid.UUID | None = None,
) -> SalesInvoice | None:
    """Return a live invoice (DRAFT included) already billing this DC."""
    stmt = select(SalesInvoice).where(
        SalesInvoice.org_id == org_id,
        SalesInvoice.delivery_challan_id == dc_id,
        SalesInvoice.deleted_at.is_(None),
        SalesInvoice.lifecycle_status.not_in(RELEASED_INVOICE_STATUSES),
    )
    if exclude_invoice_id is not None:
        stmt = stmt.where(SalesInvoice.sales_invoice_id != exclude_invoice_id)
    return session.execute(stmt.limit(1)).scalar_one_or_none()


def _require_dc(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    party_id: uuid.UUID,
    dc_id: uuid.UUID,
    exclude_invoice_id: uuid.UUID | None,
) -> DeliveryChallan:
    """Lock the DC, then check ownership, state and that no other live invoice
    bills it. Raises AppValidationError (422) with an actionable message.

    ``lock_dc_for_invoicing`` / ``find_live_invoice_on_dc`` are resolved as
    module globals at call time, so tests can swap them to prove which guard
    (row lock vs unique index) carries a race.
    """
    dc = lock_dc_for_invoicing(session, org_id=org_id, dc_id=dc_id)
    if dc is None:
        raise AppValidationError(
            f"Delivery challan {dc_id} not found. Pick an issued challan of this firm."
        )
    label = _dc_label(dc)
    if dc.firm_id != firm_id:
        raise AppValidationError(
            f"Delivery challan {label} belongs to a different firm; bill it from that firm."
        )
    if dc.party_id != party_id:
        raise AppValidationError(
            f"Delivery challan {label} was dispatched to a different customer; "
            "bill it to the customer on the challan."
        )
    if dc.status not in INVOICEABLE_DC_STATUSES:
        hint = " Issue the challan first." if dc.status == DCStatus.DRAFT.value else ""
        raise AppValidationError(
            f"Delivery challan {label} is {dc.status}; only an ISSUED or ACKNOWLEDGED "
            f"challan can be invoiced.{hint}"
        )
    other = find_live_invoice_on_dc(
        session, org_id=org_id, dc_id=dc_id, exclude_invoice_id=exclude_invoice_id
    )
    if other is not None:
        raise AppValidationError(
            f"Delivery challan {label} is already billed on invoice "
            f"{other.series}/{other.number} ({other.lifecycle_status.value}). "
            "Cancel that invoice first, or use it instead of creating another."
        )
    return dc


def _fmt_qty(qty: Decimal) -> str:
    return format(qty.normalize(), "f")


def _check_lines_match_dc(
    session: Session,
    *,
    org_id: uuid.UUID,
    dc: DeliveryChallan,
    invoice_lines: Iterable[Mapping[str, object]],
) -> None:
    """One invoice <-> one DC: stockable lines bill exactly the DC's stockable
    items and quantities. SERVICE lines on either side are ignored."""
    inv_lines = list(invoice_lines)
    dc_lines = [ln for ln in dc.lines if ln.deleted_at is None]
    item_ids = {uuid.UUID(str(ln["item_id"])) for ln in inv_lines} | {
        ln.item_id for ln in dc_lines
    }
    items = {
        it.item_id: it
        for it in session.execute(
            select(Item).where(Item.item_id.in_(item_ids), Item.org_id == org_id)
        ).scalars()
    }

    def stockable(item_id: uuid.UUID) -> bool:
        item = items.get(item_id)
        return item is not None and item.item_type != ItemType.SERVICE

    billed: dict[uuid.UUID, Decimal] = {}
    for ln in inv_lines:
        item_id = uuid.UUID(str(ln["item_id"]))
        if stockable(item_id):
            billed[item_id] = billed.get(item_id, Decimal("0")) + Decimal(str(ln["qty"]))
    dispatched: dict[uuid.UUID, Decimal] = {}
    for dl in dc_lines:
        if stockable(dl.item_id):
            dispatched[dl.item_id] = dispatched.get(dl.item_id, Decimal("0")) + Decimal(
                str(dl.qty_dispatched)
            )

    label = _dc_label(dc)
    for item_id in billed:
        if item_id not in dispatched:
            raise AppValidationError(
                f"Item {items[item_id].name} is not on delivery challan {label}; an "
                "invoice raised against a challan can only bill the goods it dispatched."
            )
    for item_id, qty in dispatched.items():
        got = billed.get(item_id, Decimal("0"))
        if got != qty:
            raise AppValidationError(
                f"Item {items[item_id].name}: invoice bills {_fmt_qty(got)} but challan "
                f"{label} dispatched {_fmt_qty(qty)}. Bill the full challan quantity "
                "(partial billing of a challan isn't supported yet)."
            )


def validate_link_for_create(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    party_id: uuid.UUID,
    dc_id: uuid.UUID,
    lines: Iterable[Mapping[str, object]],
) -> DeliveryChallan:
    """Lock + validate a DC for a new draft invoice. Call BEFORE anything that
    locks the firm row (invoice numbering)."""
    dc = _require_dc(
        session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        dc_id=dc_id,
        exclude_invoice_id=None,
    )
    _check_lines_match_dc(session, org_id=org_id, dc=dc, invoice_lines=lines)
    return dc


def revalidate_link_for_finalize(session: Session, *, invoice: SalesInvoice) -> DeliveryChallan:
    """Re-lock + re-check the DC at finalize (the caller already holds the
    invoice row lock). Defence in depth: the DC must still be dispatched,
    still the invoice's firm/party, and not billed by any other live invoice.
    """
    dc_id = invoice.delivery_challan_id
    if dc_id is None:  # pragma: no cover - caller routes only DC-linked here
        raise AppValidationError("Invoice is not linked to a delivery challan.")
    return _require_dc(
        session,
        org_id=invoice.org_id,
        firm_id=invoice.firm_id,
        party_id=invoice.party_id,
        dc_id=dc_id,
        exclude_invoice_id=invoice.sales_invoice_id,
    )


def translate_link_integrity_error(exc: IntegrityError, *, dc_id: uuid.UUID | None) -> None:
    """Raise a 422 if ``exc`` is the DC-link unique index; otherwise return so
    the caller re-raises the original error."""
    if dc_id is not None and LINK_UNIQUE_INDEX in str(exc.orig):
        raise AppValidationError(
            f"Delivery challan {dc_id} was billed on another invoice concurrently; "
            "refresh and pick a challan that isn't invoiced yet."
        ) from exc


__all__ = [
    "INVOICEABLE_DC_STATUSES",
    "LINK_UNIQUE_INDEX",
    "RELEASED_INVOICE_STATUSES",
    "find_live_invoice_on_dc",
    "lock_dc_for_invoicing",
    "revalidate_link_for_finalize",
    "translate_link_integrity_error",
    "validate_link_for_create",
]

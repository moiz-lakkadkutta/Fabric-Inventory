"""E2 (BL-01): backfill Customer Advances (2500) ledger for all existing orgs.

BACKGROUND
----------
``post_receipt`` now splits the credit side of a receipt voucher:
  DR Cash/Bank (1000/1100)        full receipt amount
  CR Sundry Debtors / AR (1200)   allocated portion (invoices cleared)
  CR Customer Advances (2500)     remaining / excess (on-account advance)

Ledger 2500 "Customer Advances" was added to ``_SYSTEM_LEDGERS``
in ``seed_service.py``.  New orgs created after this migration ship will
receive it automatically at signup (``seed_coa`` is called from
``/auth/signup``).  Orgs created before this migration never had it; this
migration backfills the row for every existing live org.

PATTERN
-------
Same backfill pattern as ``e1_itc_ledger`` (ledger 1400): iterate over
``organization``, call ``seed_coa`` (idempotent — skips codes that already
exist), flush.

IDEMPOTENT
----------
``seed_coa`` checks for existing ledger codes per org before inserting,
so re-running this migration is a no-op.

DOWNGRADE
---------
Removes the 2500 ledger rows, but only if no voucher_line references them.
If any voucher_line already references a 2500 ledger (meaning at least one
over-receipt or pure advance has been posted via the new path), downgrade
raises — the data cannot safely be removed without reversing those vouchers
first. The FK `voucher_line.ledger_id → ledger.ledger_id ON DELETE RESTRICT`
provides an additional backstop at the DB layer.

Revision ID: e2_customer_advances
Revises: e1_itc_ledger
Create Date: 2026-06-26
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e2_customer_advances"
down_revision: str | Sequence[str] | None = "e1_itc_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _backfill_customer_advances_ledger(conn: sa.Connection) -> None:
    """Idempotent backfill: ensure the 2500 Customer Advances ledger exists for
    every live org.  ``seed_coa`` checks for existing codes per org and only
    inserts absent rows — running this twice is a no-op.
    """
    rows = conn.execute(sa.text("SELECT org_id FROM organization WHERE deleted_at IS NULL")).all()
    org_ids: list[uuid.UUID] = [uuid.UUID(str(r[0])) for r in rows]

    if not org_ids:
        return  # Fresh install — no existing orgs to patch.

    from sqlalchemy.orm import Session

    from app.service.seed_service import seed_coa

    with Session(bind=conn) as session:
        for org_id in org_ids:
            # idempotent: seed_coa skips any ledger code already present.
            seed_coa(session, org_id=org_id)
        session.flush()


def upgrade() -> None:
    conn = op.get_bind()
    _backfill_customer_advances_ledger(conn)


def downgrade() -> None:
    """Remove the 2500 ledger rows, but only if no voucher_line references them.

    If any voucher_line references a 2500 ledger (i.e. at least one over-receipt
    or advance has been posted via the new path), raise — those rows cannot be
    safely deleted without first reversing the vouchers.

    Note: the FK ``voucher_line.ledger_id → ledger.ledger_id`` carries
    ``ON DELETE RESTRICT``, so Postgres would refuse the DELETE anyway; the
    explicit count + RuntimeError gives a cleaner human-readable message.
    """
    conn = op.get_bind()

    # Check for references.
    referenced = conn.execute(
        sa.text(
            """
            SELECT count(*)
            FROM voucher_line vl
            JOIN ledger l ON l.ledger_id = vl.ledger_id
            WHERE l.code = '2500'
              AND l.firm_id IS NULL
            """
        )
    ).scalar_one()

    if referenced:
        raise RuntimeError(
            f"e2_customer_advances downgrade blocked: {referenced} voucher_line row(s) reference "
            "the 2500 Customer Advances ledger.  Reverse the affected receipts/advance vouchers "
            "first before downgrading."
        )

    conn.execute(sa.text("DELETE FROM ledger WHERE code = '2500' AND firm_id IS NULL"))

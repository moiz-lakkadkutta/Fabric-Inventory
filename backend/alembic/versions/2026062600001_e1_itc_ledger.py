"""E1 (GL-1): backfill ITC Receivable (1400) ledger for all existing orgs.

BACKGROUND
----------
``post_pi`` now creates a balanced ``PURCHASE_INVOICE`` GL voucher:
  DR 1300 Inventory          net taxable value
  DR 1400 ITC Receivable     input GST amount  (forward charge only)
  CR 2000 Sundry Creditors   gross payable

Ledger 1400 "ITC Receivable (Input GST)" was added to ``_SYSTEM_LEDGERS``
in ``seed_service.py``.  New orgs created after this migration ship will
receive it automatically at signup (``seed_coa`` is called from
``/auth/signup``).  Orgs created before this migration never had it; this
migration backfills the row for every existing live org.

PATTERN
-------
Same backfill pattern as ``c3_stock_adj_gl`` (ledger 5350) and
``tfix6_backfill_pii_read``: iterate over ``organization``, call
``seed_coa`` (idempotent — skips codes that already exist), flush.

IDEMPOTENT
----------
``seed_coa`` checks for existing ledger codes per org before inserting,
so re-running this migration is a no-op.

DOWNGRADE
---------
Removes the 1400 ledger rows for orgs that have no voucher_line
referencing them. If any voucher_line already references a 1400 ledger
(meaning post_pi has run on at least one PI), downgrade raises — the
data cannot safely be removed without reversing those vouchers first.

Revision ID: e1_itc_ledger
Revises: f1_reencrypt_pii
Create Date: 2026-06-26
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e1_itc_ledger"
down_revision: str | Sequence[str] | None = "f1_reencrypt_pii"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _backfill_itc_ledger(conn: sa.Connection) -> None:
    """Idempotent backfill: ensure the 1400 ITC Receivable ledger exists for
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
    _backfill_itc_ledger(conn)


def downgrade() -> None:
    """Remove the 1400 ledger rows, but only if no voucher_line references them.

    If any voucher_line references a 1400 ledger (i.e. at least one PI has been
    posted via the new path), raise — those rows cannot be safely deleted without
    first reversing the vouchers.
    """
    conn = op.get_bind()

    # Check for references.
    referenced = conn.execute(
        sa.text(
            """
            SELECT count(*)
            FROM voucher_line vl
            JOIN ledger l ON l.ledger_id = vl.ledger_id
            WHERE l.code = '1400'
              AND l.firm_id IS NULL
            """
        )
    ).scalar_one()

    if referenced:
        raise RuntimeError(
            f"e1_itc_ledger downgrade blocked: {referenced} voucher_line row(s) reference "
            "the 1400 ITC Receivable ledger.  Reverse the purchase vouchers first."
        )

    # The `voucher_line.ledger_id` FK references `ledger.ledger_id` with
    # ON DELETE RESTRICT, so even without the explicit check above Postgres
    # would refuse to delete a ledger row that is still referenced by any
    # voucher_line.  The explicit count + RuntimeError above gives a cleaner
    # error message than the FK violation would.
    conn.execute(sa.text("DELETE FROM ledger WHERE code = '1400' AND firm_id IS NULL"))

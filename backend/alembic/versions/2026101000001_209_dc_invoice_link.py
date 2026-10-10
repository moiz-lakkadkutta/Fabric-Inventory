"""#209 / DEBT-02: one live invoice per delivery challan.

Adds a partial-unique index on ``sales_invoice`` guaranteeing that at most ONE
live invoice links to a given delivery challan:

    uq_sales_invoice_delivery_challan_live
      ON sales_invoice (delivery_challan_id)
      WHERE delivery_challan_id IS NOT NULL
        AND deleted_at IS NULL
        AND lifecycle_status NOT IN ('CANCELLED', 'DISCARDED')

Why: ``issue_dc`` relieves stock; a DC-linked invoice's finalize posts COGS
from the DC's stock movements (``sales_service._post_cogs_for_dc_invoice``).
Two live invoices on one DC would post COGS twice for one dispatch. The
service layer takes ``SELECT ... FOR UPDATE`` on the DC row before its "is
this DC already billed?" check (``dc_invoice_link_service``); this index is
the concurrency backstop, translated to a 422 by the service.

DRAFT invoices count (a DC can't sit on two drafts). CANCELLED / DISCARDED /
soft-deleted invoices release the DC so it can be billed again. Enum literals
are cast explicitly (``'X'::invoice_lifecycle_status``) — comparing the enum
column to enum constants is IMMUTABLE, as an index predicate requires (an
enum -> text cast would not be).

Pre-flight guard (fail-closed, read-only): if two live invoices already share
a DC the CREATE UNIQUE INDEX would fail with an opaque error. We detect that
first and raise an actionable RuntimeError naming the challans; nothing is
mutated. None are expected: before this change no code path set
``sales_invoice.delivery_challan_id``.

Lock note: plain CREATE UNIQUE INDEX takes a SHARE lock on ``sales_invoice``
(sub-second at dogfood scale); CONCURRENTLY can't run inside Alembic's
transaction.

Backward-compatible: index-only. Downgrade drops the index.

Revision ID: 209_dc_invoice_link
Revises: 203_grn_accrual
Create Date: 2026-10-10
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "209_dc_invoice_link"
down_revision: str = "203_grn_accrual"
branch_labels = None
depends_on = None

_INDEX_NAME = "uq_sales_invoice_delivery_challan_live"

_LIVE_PREDICATE = (
    "delivery_challan_id IS NOT NULL "
    "AND deleted_at IS NULL "
    "AND lifecycle_status NOT IN ("
    "'CANCELLED'::invoice_lifecycle_status, 'DISCARDED'::invoice_lifecycle_status)"
)

_DUP_DETECT_SQL = f"""
    SELECT delivery_challan_id::text, count(*)
    FROM sales_invoice
    WHERE {_LIVE_PREDICATE}
    GROUP BY delivery_challan_id
    HAVING count(*) > 1
    ORDER BY delivery_challan_id
    LIMIT 20
"""


def upgrade() -> None:
    conn = op.get_bind()
    dups = conn.execute(sa.text(_DUP_DETECT_SQL)).all()
    if dups:
        listed = ", ".join(f"{dc_id} ({n} invoices)" for dc_id, n in dups)
        raise RuntimeError(
            "#209: these delivery challans are linked to more than one live "
            f"(non-cancelled, non-deleted) sales invoice: {listed}. Cancel or "
            "soft-delete the extra invoices (keep one per challan) and re-run the "
            "migration. No data was changed."
        )

    op.execute(
        f"""
        CREATE UNIQUE INDEX {_INDEX_NAME}
            ON sales_invoice (delivery_challan_id)
            WHERE {_LIVE_PREDICATE}
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")

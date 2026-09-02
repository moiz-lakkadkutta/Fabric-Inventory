"""#190 concurrency backstop: at most one non-deleted GL posting per source doc.

Adds a partial-unique index on `voucher` guaranteeing that at most ONE
non-deleted voucher exists per (org_id, voucher_type, reference_type,
reference_id) for the two voucher types where a 1:1 relationship with the
source document is an invariant: SALES_INVOICE and COGS_SALE.

This is the DB backstop for the state-check-then-write race fixed in the
service layer (SELECT ... FOR UPDATE on the aggregate row). If the row lock
is ever bypassed, this index rejects the loser's INSERT, which
`accounting_service` translates into a clean 409 InvoiceStateError.

Deliberately EXCLUDED from the predicate:
  - PURCHASE_INVOICE: `accounting_service.reverse_purchase_invoice_gl` posts a
    legitimate SECOND voucher with the same reference_id (the void reversal),
    so a unique on it would break the void path.
  - RECEIPT / PAYMENT / JOURNAL: reference_id IS NULL on those headers (many
    receipts/payments per party/day are legal), so they are filtered out by
    `reference_id IS NOT NULL`.

Pre-flight guard: if duplicate SALES_INVOICE/COGS_SALE postings already exist,
the CREATE UNIQUE INDEX would fail with an opaque error. We detect them first
and raise a loud, actionable RuntimeError instructing the operator to run the
#190 data repair (schema/patches/190-dedupe-postings.sql) before migrating.
We never silently mutate the books inside a migration.

Lock note: plain CREATE UNIQUE INDEX takes a SHARE lock on `voucher`; at
dev/dogfood scale this is sub-second. CONCURRENTLY is not usable here because
Alembic runs migrations inside a transaction.

Revision ID: 190_voucher_posting_unique
Revises: f2_ap_payment_schema
Create Date: 2026-09-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "190_voucher_posting_unique"
down_revision: str = "f2_ap_payment_schema"
branch_labels = None
depends_on = None

_INDEX_NAME = "uq_voucher_one_posting_per_ref"

# Same detection query used by the #190 data repair. `narration NOT LIKE
# 'Reversal of%'` excludes reversal vouchers (defense-in-depth; the predicate
# already excludes PURCHASE_INVOICE, but SALES/COGS reversals, should any exist,
# must not trip the guard). count(*) > 1 within a group = corruption.
_DUP_DETECT_SQL = """
    SELECT count(*) FROM (
        SELECT 1
        FROM voucher v
        WHERE v.reference_id IS NOT NULL
          AND v.deleted_at IS NULL
          AND v.voucher_type IN ('SALES_INVOICE', 'COGS_SALE')
          AND v.narration NOT LIKE 'Reversal of%'
        GROUP BY v.org_id, v.voucher_type, v.reference_type, v.reference_id
        HAVING count(*) > 1
    ) dups
"""


def upgrade() -> None:
    conn = op.get_bind()
    dup_groups = conn.execute(sa.text(_DUP_DETECT_SQL)).scalar()
    if dup_groups and dup_groups > 0:
        raise RuntimeError(
            f"#190: {dup_groups} duplicate SALES_INVOICE/COGS_SALE posting group(s) "
            "exist — run the #190 data repair first "
            "(schema/patches/190-dedupe-postings.sql) before applying this migration."
        )

    op.execute(
        f"""
        CREATE UNIQUE INDEX {_INDEX_NAME}
            ON voucher (org_id, voucher_type, reference_type, reference_id)
            WHERE deleted_at IS NULL
              AND reference_id IS NOT NULL
              AND voucher_type IN ('SALES_INVOICE', 'COGS_SALE')
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")

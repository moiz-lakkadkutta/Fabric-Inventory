"""#199 Cancel path for finalized sales invoices (reversing voucher).

Adds the schema this issue needs:

1. Two nullable columns on ``sales_invoice`` recording the cancellation:
     - ``cancelled_at TIMESTAMPTZ`` — when the invoice was cancelled (UTC).
     - ``cancel_reason TEXT``       — free-text reason (spec §7 requires one).
   Both NULL ⇒ never cancelled. Backward-compatible, no backfill.

2. A partial-unique index guaranteeing at most ONE non-deleted reversal
   voucher per original voucher:
     uq_voucher_sales_invoice_reversal
       ON voucher (org_id, reference_id)
       WHERE reference_type = 'sales_invoice_reversal' AND deleted_at IS NULL

   ``sales_service.cancel_invoice`` posts each reversal with
   ``reference_type='sales_invoice_reversal'`` and ``reference_id=<the
   ORIGINAL voucher's id>`` (a positive "already reversed" marker instead of
   PI-void's fragile ``narration NOT LIKE 'Reversal of%'`` filter). This
   index is the concurrency backstop: if two cancels race, the loser's
   INSERT trips it and is translated to a 409, exactly one reversal survives.

   Interaction with #190's ``uq_voucher_one_posting_per_ref``: that index
   only covers ``voucher_type IN ('SALES_INVOICE','COGS_SALE')`` keyed on
   (org, voucher_type, reference_type, reference_id). The reversals do NOT
   collide with it because they use a DIFFERENT reference_type
   ('sales_invoice_reversal' vs the original's 'sales_invoice') AND a
   different reference_id (the original voucher_id, not the invoice_id) — and
   the sales-side reversal is a CREDIT_NOTE voucher_type, which #190's
   predicate excludes entirely.

Revision ID: 199_invoice_cancel
Revises: 198a_cogs_coa_group
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "199_invoice_cancel"
down_revision: str = "198a_cogs_coa_group"
branch_labels = None
depends_on = None

_REVERSAL_INDEX = "uq_voucher_sales_invoice_reversal"


def upgrade() -> None:
    op.add_column(
        "sales_invoice",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sales_invoice",
        sa.Column("cancel_reason", sa.Text(), nullable=True),
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX {_REVERSAL_INDEX}
            ON voucher (org_id, reference_id)
            WHERE reference_type = 'sales_invoice_reversal'
              AND deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_REVERSAL_INDEX}")
    op.drop_column("sales_invoice", "cancel_reason")
    op.drop_column("sales_invoice", "cancelled_at")

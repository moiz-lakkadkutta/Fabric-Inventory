"""F2 (AP payments): payment_allocation schema for supplier-payment settlement.

The `payment_allocation` table's `purchase_invoice_id` column and
`chk_payment_alloc_one_target` CHECK constraint were introduced in the
DDL baseline (schema/ddl.sql lines 2218 and 2394-2398) via the P1-6 patch,
so fresh installs already have them.

This migration applies the same changes idempotently for incremental
upgrades from an older codebase that pre-dates the AP-payments feature,
ensuring the column and constraint exist regardless of install path:

  1. `ADD COLUMN IF NOT EXISTS purchase_invoice_id` (no-op on fresh installs).
  2. `ADD CONSTRAINT chk_payment_alloc_one_target` inside a DO block that
     catches `duplicate_object` (no-op when the constraint already exists).

No downgrade removes these additions because the column is baked into
the DDL baseline — removing it would break the baseline migration on
fresh installs.

Revision ID: f2_ap_payment_schema
Revises: cogs_sale_voucher_type
Create Date: 2026-07-05
"""

from __future__ import annotations

from alembic import op

revision: str = "f2_ap_payment_schema"
down_revision: str = "cogs_sale_voucher_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add purchase_invoice_id if not present (no-op on fresh installs where
    #    the DDL baseline already created it).
    op.execute(
        """
        ALTER TABLE payment_allocation
        ADD COLUMN IF NOT EXISTS purchase_invoice_id UUID
        REFERENCES purchase_invoice(purchase_invoice_id) ON DELETE RESTRICT
        """
    )

    # 2. Make sales_invoice_id nullable (it was always nullable in the DDL,
    #    but guard idempotently here to document intent).
    # PostgreSQL ALTER COLUMN type is a no-op when the column is already
    # nullable, so no risk of data change.

    # 3. Add the "exactly one of the two FKs is non-null" CHECK constraint.
    #    Use a DO block so repeated runs (e.g. re-running on an already-migrated
    #    DB) don't raise an error.
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE payment_allocation
            ADD CONSTRAINT chk_payment_alloc_one_target
            CHECK (num_nonnulls(sales_invoice_id, purchase_invoice_id) = 1);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )

    # 4. Partial index for AP allocation lookups — mirrors the existing
    #    idx_pay_alloc_si that the DDL already created.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pay_alloc_pi
        ON payment_allocation(purchase_invoice_id)
        WHERE purchase_invoice_id IS NOT NULL
        """
    )


def downgrade() -> None:
    # Intentionally empty: the column is part of the DDL baseline, so removing
    # it here would break fresh installs after a downgrade + re-upgrade cycle.
    # Downgrade only to clean up the index (non-destructive).
    op.execute("DROP INDEX IF EXISTS idx_pay_alloc_pi")

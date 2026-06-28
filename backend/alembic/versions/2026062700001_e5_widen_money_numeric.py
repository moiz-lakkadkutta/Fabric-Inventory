"""E5 (BL-03): widen every scale-2 money column from NUMERIC(15,2) to NUMERIC(18,2).

BACKGROUND
----------
CLAUDE.md mandates: "Always NUMERIC(18,2) in Postgres. Never float."
All 22 money (scale=2) columns were created as NUMERIC(15,2), capping
the representable value at ~₹9.99 trillion (13 digits before the decimal).
BL-02 showed that a legitimately large line amount could overflow this,
producing an unhandled 500.  NUMERIC(18,2) allows 16 digits before the
decimal (~₹9.99 quadrillion), which comfortably covers any real business
transaction.

SCOPE
-----
Only NUMERIC(15, 2) → NUMERIC(18, 2) columns are widened.  Quantity
columns (NUMERIC(15,3) and NUMERIC(15,4) — 51 of them) are intentionally
unchanged; they are not money.

COLUMNS (22 total across 12 tables):
  accounting : voucher.total_debit, voucher.total_credit
               voucher_line.amount
  masters    : party.credit_limit, ledger.opening_balance
  sales      : sales_order.total_amount, so_line.line_amount
               delivery_challan.total_amount
               sales_invoice.invoice_amount, sales_invoice.gst_amount
               si_line.line_amount, si_line.gst_amount
  procurement: purchase_order.total_amount, po_line.line_amount
               grn.total_amount
               purchase_invoice.invoice_amount, purchase_invoice.gst_amount
               pi_line.line_amount, pi_line.gst_amount
  banking    : bank_account.balance, cheque.amount
  manufacturing: manufacturing_order.cost_pool

SAFETY
------
Widening precision with the same scale is always non-lossy — Postgres
ALTER TYPE NUMERIC(15,2) → NUMERIC(18,2) never truncates existing data.
No index rebuild is triggered by this change alone.

DOWNGRADE NOTE
--------------
Reversing to NUMERIC(15,2) is safe in dev (no data exceeds the old cap).
In production, only roll back via backup if any live value has grown
beyond 13 digits before the decimal; those would be silently truncated
by Postgres on downgrade.

Revision ID: e5_widen_money_numeric
Revises: e2_customer_advances
Create Date: 2026-06-27
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "e5_widen_money_numeric"
down_revision: str = "e2_customer_advances"
branch_labels = None
depends_on = None

_OLD = sa.Numeric(15, 2)
_NEW = sa.Numeric(18, 2)


def upgrade() -> None:
    # ── accounting ──────────────────────────────────────────────────────
    op.alter_column(
        "voucher",
        "total_debit",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=True,
    )
    op.alter_column(
        "voucher",
        "total_credit",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=True,
    )
    op.alter_column(
        "voucher_line",
        "amount",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=False,
    )

    # ── masters ──────────────────────────────────────────────────────────
    op.alter_column(
        "party",
        "credit_limit",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=True,
    )
    op.alter_column(
        "ledger",
        "opening_balance",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=True,
    )

    # ── sales ────────────────────────────────────────────────────────────
    op.alter_column(
        "sales_order",
        "total_amount",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=True,
    )
    op.alter_column(
        "so_line",
        "line_amount",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=True,
    )
    op.alter_column(
        "delivery_challan",
        "total_amount",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=True,
    )
    op.alter_column(
        "sales_invoice",
        "invoice_amount",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=True,
    )
    op.alter_column(
        "sales_invoice",
        "gst_amount",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=True,
    )
    op.alter_column(
        "si_line",
        "line_amount",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=True,
    )
    op.alter_column(
        "si_line",
        "gst_amount",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=True,
    )

    # ── procurement ──────────────────────────────────────────────────────
    op.alter_column(
        "purchase_order",
        "total_amount",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=True,
    )
    op.alter_column(
        "po_line",
        "line_amount",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=True,
    )
    op.alter_column(
        "grn",
        "total_amount",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=True,
    )
    op.alter_column(
        "purchase_invoice",
        "invoice_amount",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=True,
    )
    op.alter_column(
        "purchase_invoice",
        "gst_amount",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=True,
    )
    op.alter_column(
        "pi_line",
        "line_amount",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=True,
    )
    op.alter_column(
        "pi_line",
        "gst_amount",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=True,
    )

    # ── banking ──────────────────────────────────────────────────────────
    op.alter_column(
        "bank_account",
        "balance",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=True,
    )
    op.alter_column(
        "cheque",
        "amount",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=True,
    )

    # ── manufacturing ─────────────────────────────────────────────────────
    op.alter_column(
        "manufacturing_order",
        "cost_pool",
        type_=_NEW,
        existing_type=_OLD,
        existing_nullable=True,
    )


def downgrade() -> None:
    # Reverse each column to NUMERIC(15,2).
    # WARNING: in production, only downgrade via backup if any live value
    # exceeds 13 digits before the decimal.  Postgres will silently raise
    # "numeric field overflow" if such a value is present.

    # ── manufacturing ─────────────────────────────────────────────────────
    op.alter_column(
        "manufacturing_order",
        "cost_pool",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=True,
    )

    # ── banking ──────────────────────────────────────────────────────────
    op.alter_column(
        "cheque",
        "amount",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=True,
    )
    op.alter_column(
        "bank_account",
        "balance",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=True,
    )

    # ── procurement ──────────────────────────────────────────────────────
    op.alter_column(
        "pi_line",
        "gst_amount",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=True,
    )
    op.alter_column(
        "pi_line",
        "line_amount",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=True,
    )
    op.alter_column(
        "purchase_invoice",
        "gst_amount",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=True,
    )
    op.alter_column(
        "purchase_invoice",
        "invoice_amount",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=True,
    )
    op.alter_column(
        "grn",
        "total_amount",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=True,
    )
    op.alter_column(
        "po_line",
        "line_amount",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=True,
    )
    op.alter_column(
        "purchase_order",
        "total_amount",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=True,
    )

    # ── sales ────────────────────────────────────────────────────────────
    op.alter_column(
        "si_line",
        "gst_amount",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=True,
    )
    op.alter_column(
        "si_line",
        "line_amount",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=True,
    )
    op.alter_column(
        "sales_invoice",
        "gst_amount",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=True,
    )
    op.alter_column(
        "sales_invoice",
        "invoice_amount",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=True,
    )
    op.alter_column(
        "delivery_challan",
        "total_amount",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=True,
    )
    op.alter_column(
        "so_line",
        "line_amount",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=True,
    )
    op.alter_column(
        "sales_order",
        "total_amount",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=True,
    )

    # ── masters ──────────────────────────────────────────────────────────
    op.alter_column(
        "ledger",
        "opening_balance",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=True,
    )
    op.alter_column(
        "party",
        "credit_limit",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=True,
    )

    # ── accounting ──────────────────────────────────────────────────────
    op.alter_column(
        "voucher_line",
        "amount",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=False,
    )
    op.alter_column(
        "voucher",
        "total_credit",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=True,
    )
    op.alter_column(
        "voucher",
        "total_debit",
        type_=_OLD,
        existing_type=_NEW,
        existing_nullable=True,
    )

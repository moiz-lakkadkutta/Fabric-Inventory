"""TASK-TR-B3: bank-statement reconciliation — stamp vouchers as reconciled.

B3 adds two columns to ``voucher`` that capture the bank-statement
reconciliation state:

1. ``bank_reconciled_at TIMESTAMPTZ NULL`` — the moment an operator
   matched this voucher (a RECEIPT or PAYMENT) against a row on the
   bank's statement. NULL means "not yet reconciled". Reconciliation
   does NOT change the GL: no new voucher lines, no posting reversal.
   The trial balance is therefore unaffected by flipping this flag.

2. ``statement_ref TEXT NULL`` — the bank-side reference (typically
   the bank's UTR / cheque number / NEFT ref / row index from the
   imported CSV) the operator linked this voucher to. Free-form so the
   adapter for any bank's statement format (HDFC PDF, SBI CSV, ICICI
   MT940) can stamp whatever identifier the bank carries without
   needing a schema migration per adapter.

Both columns are NULLable with no server default — existing rows stay
NULL on upgrade (every pre-B3 voucher is implicitly "not reconciled
against any statement"), so the migration is backward-compatible. The
posted invoice flow (post_invoice_to_gl), receipt flow (post_receipt)
and JV flow (post_journal_voucher) don't touch these columns at all;
only the new bank-reconciliation service does.

Money-touching note: this is a money-adjacent schema change but NOT a
money path side effect. ``bank_reconciled_at`` is a *flag* on existing
vouchers. The reconciliation endpoint stamps the flag in-place; it
never edits ``total_debit`` / ``total_credit`` / ``voucher_line.amount``,
and it never posts new GL lines. Trial-balance correctness is invariant
under the B3 flow.

Revision ID: task_tr_b3_bank_recon
Revises: task_tr_a11_mo_completion
Create Date: 2026-05-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "task_tr_b3_bank_recon"
down_revision: str | Sequence[str] | None = "task_tr_a11_mo_completion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Both columns NULLable, no server default — existing rows carry
    # NULL on upgrade. Single ALTER per column keeps the lock window
    # short (PG holds AccessExclusive only for the metadata flip; no
    # table rewrite for adding NULLable columns without a default).
    op.add_column(
        "voucher",
        sa.Column("bank_reconciled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "voucher",
        sa.Column("statement_ref", sa.Text(), nullable=True),
    )
    # Partial index on reconciled vouchers — the bank-recon hub will
    # ask "which vouchers are reconciled against this bank account?"
    # often enough that a small index pays for itself. NULL-skipping
    # keeps the index narrow.
    op.create_index(
        "idx_voucher_bank_reconciled_at",
        "voucher",
        ["bank_reconciled_at"],
        postgresql_where=sa.text("bank_reconciled_at IS NOT NULL"),
    )


def downgrade() -> None:
    # Reversible: drop the index then the columns in the reverse order
    # they were added. Data loss is expected on downgrade — the
    # reconciliation stamps had nowhere else to land before this migration.
    op.drop_index("idx_voucher_bank_reconciled_at", table_name="voucher")
    op.drop_column("voucher", "statement_ref")
    op.drop_column("voucher", "bank_reconciled_at")

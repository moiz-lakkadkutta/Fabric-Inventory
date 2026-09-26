"""#201 bank reconciliation: one bank account per GL sub-ledger.

Adds a partial-unique index on `bank_account` guaranteeing that at most ONE
non-deleted bank account exists per `ledger_id`. This makes the
voucher-line → bank-account mapping the reconciliation fix relies on a
true 1:1 relationship.

Why this matters (#201): `bank_reconciliation_service` derives "which bank
account does this voucher belong to" from the voucher_line that lands on
the account's `ledger_id`. If two bank accounts could share one ledger,
that mapping would be ambiguous and a voucher could be reconciled against
the wrong account. The service layer also enforces this
(`banking_service.create_bank_account` rejects a duplicate ledger link);
this index is the concurrency backstop so two overlapping creates can't
both win the check-then-insert race.

Pre-flight guard: if duplicate (non-deleted) bank accounts already share a
ledger, the CREATE UNIQUE INDEX would fail with an opaque error. We detect
them first and raise a loud, actionable RuntimeError. The banking feature
is young so none are expected in practice.

Lock note: plain CREATE UNIQUE INDEX takes a SHARE lock on `bank_account`;
at dev/dogfood scale this is sub-second. CONCURRENTLY is not usable here
because Alembic runs migrations inside a transaction.

Backward-compatible: no column changes, index-only. Downgrade drops the index.

Revision ID: 201_bank_account_ledger_unique
Revises: t208_email_lowercase
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "201_bank_account_ledger_unique"
down_revision: str = "t208_email_lowercase"
branch_labels = None
depends_on = None

_INDEX_NAME = "uq_bank_account_ledger"

_DUP_DETECT_SQL = """
    SELECT count(*) FROM (
        SELECT 1
        FROM bank_account
        WHERE deleted_at IS NULL
        GROUP BY ledger_id
        HAVING count(*) > 1
    ) dups
"""


def upgrade() -> None:
    conn = op.get_bind()
    dup_groups = conn.execute(sa.text(_DUP_DETECT_SQL)).scalar()
    if dup_groups and dup_groups > 0:
        raise RuntimeError(
            f"#201: {dup_groups} ledger(s) are linked to more than one non-deleted "
            "bank account — resolve the duplicates (soft-delete or re-point to a "
            "distinct sub-ledger) before applying this migration."
        )

    op.execute(
        f"""
        CREATE UNIQUE INDEX {_INDEX_NAME}
            ON bank_account (ledger_id)
            WHERE deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")

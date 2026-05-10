"""TASK-CUT-104 (P1-2): voucher.party_id column for receipt party preservation.

Audit-2026-05-10 § P1-2 found receipts with no open invoices lose
`party_name` in `GET /receipts` because the list mapper derived party
only via `payment_allocation` → `sales_invoice` → `party`. Receipts with
zero allocations have no link, so the party is silently lost.

Fix: voucher table grows a NULLABLE `party_id` column (UUID, FK to
`party.party_id` ON DELETE SET NULL). `receipt_service.post_receipt`
populates it. `list_receipts_with_details` prefers
`voucher.party_id` (with a fallback to the join for legacy rows that
pre-date this migration).

NULLABLE with no default → instant DDL, no table rewrite, safe deploy.
DO NOT make it NOT NULL — a JOURNAL or CONTRA voucher has no single
party (and never will).

Index `(org_id, firm_id, party_id)` supports party-statement reports
(future TASK-CUT-302 remaining-Reports BE) and FIFO lookups.

Revision ID: task_cut_104_voucher_party_id
Revises: task_int_9_app_role_split
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "task_cut_104_voucher_party_id"
down_revision: str | Sequence[str] | None = "task_cut_105_reports_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "voucher",
        sa.Column(
            "party_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("party.party_id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_voucher_org_firm_party",
        "voucher",
        ["org_id", "firm_id", "party_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_voucher_org_firm_party", table_name="voucher")
    op.drop_column("voucher", "party_id")

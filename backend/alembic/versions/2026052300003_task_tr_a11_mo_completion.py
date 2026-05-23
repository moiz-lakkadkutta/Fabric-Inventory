"""TASK-TR-A11: MO completion — new voucher_type for finished-goods receipt.

A11 settles WIP on MO completion: DR ``1300 Inventory`` (finished goods)
/ CR ``1310 Work-in-Process``. The existing ``voucher_type`` Postgres
enum carries SALES_INVOICE / PURCHASE_INVOICE / PAYMENT / RECEIPT /
JOURNAL / CONTRA / DEBIT_NOTE / CREDIT_NOTE / OPENING_BAL /
MATERIAL_ISSUE — none of which fit "DR FG-Inventory / CR WIP" semantics
(MATERIAL_ISSUE is the mirror leg for raw-material issue, not the
finished-goods receipt). A dedicated ``MANUFACTURING_COMPLETION`` value
keeps:

  - Trial balance drill-down legible (one voucher_type per source doc).
  - The voucher-number partition unique
    ``(org_id, firm_id, voucher_type, series, number)`` segregated from
    other types so the MO-completion series can run independently of
    MI/JV/SI numbering.

``ALTER TYPE voucher_type ADD VALUE`` is forward-only (Postgres
restriction); the downgrade docstring notes the value lingers harmlessly
post-downgrade (no rows reference it once a downgrade has dropped the
upstream code path).

Revision ID: task_tr_a11_mo_completion
Revises: task_tr_a07_polish
Create Date: 2026-05-23
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "task_tr_a11_mo_completion"
down_revision: str | Sequence[str] | None = "task_tr_a08_fu_itemids"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ``IF NOT EXISTS`` keeps this re-runnable on a partially applied DB
    # — same shape as the A06 enum extension.
    op.execute("ALTER TYPE voucher_type ADD VALUE IF NOT EXISTS 'MANUFACTURING_COMPLETION'")


def downgrade() -> None:
    # ``ALTER TYPE ... DROP VALUE`` is not supported in Postgres — enum
    # values are forward-only. ``MANUFACTURING_COMPLETION`` will linger on
    # ``voucher_type`` after a downgrade. Harmless: no rows reference it
    # post-downgrade (the upstream A11 service is gone too).
    pass

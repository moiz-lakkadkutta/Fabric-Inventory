"""TASK-TR-SEC1: add `organization.encrypted_dek` for PII envelope encryption.

The new field-encryption path (AES-256-GCM with per-org Data Encryption
Keys, wrapped by a master KEK) requires every organization to carry a
DEK on its row. The DEK is the symmetric key used to encrypt PII
columns (party.gstin / pan / phone, bank_account.account_number,
firm.gstin / pan / cin / tan, app_user.mfa_secret).

This migration:

1. Adds ``organization.encrypted_dek BYTEA NULL`` first (so existing
   rows don't blow up the ``NOT NULL`` constraint mid-upgrade).
2. Backfills a fresh DEK for every existing org row, wrapping it with
   the master KEK and using ``org_id`` bytes as AAD — exactly the same
   path ``app.utils.crypto.wrap_dek`` produces at runtime, so the row
   format is interchangeable between migration-time and signup-time
   minting.
3. Flips the column to ``NOT NULL`` once every row is populated.

The KEK is loaded the same way as the runtime app — env var
``PII_MASTER_KEY`` (base64, 32 bytes). In dev / staging the documented
fallback in ``app.utils.crypto`` is used, so a freshly-cloned dev
checkout migrates cleanly without extra steps. Prod will already have
``PII_MASTER_KEY`` set in ``/opt/fabric/.env.production`` before the
deploy that ships this migration (see deployment runbook).

Revision ID: task_tr_sec1_organization_dek
Revises: task_cut_402_user_migration
Create Date: 2026-05-15
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.utils.crypto import generate_dek, wrap_dek

revision: str = "task_tr_sec1_organization_dek"
down_revision: str | Sequence[str] | None = "task_cut_402_user_migration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add the column nullable — existing rows have no DEK yet.
    op.add_column(
        "organization",
        sa.Column("encrypted_dek", sa.LargeBinary(), nullable=True),
    )

    # 2. Backfill: mint a fresh DEK per existing org, wrap with the
    #    master KEK (AAD = org_id), write to the row. The migration role
    #    is BYPASSRLS so we don't need to SET app.current_org_id per row.
    conn = op.get_bind()
    org_ids: list[uuid.UUID] = [
        row[0] for row in conn.execute(sa.text("SELECT org_id FROM organization")).all()
    ]
    for org_id in org_ids:
        dek = generate_dek()
        blob = wrap_dek(dek, org_id=org_id)
        conn.execute(
            sa.text("UPDATE organization SET encrypted_dek = :blob WHERE org_id = :org_id"),
            {"blob": blob, "org_id": org_id},
        )

    # 3. NOT NULL going forward. Signup mints a DEK before INSERT so the
    #    constraint never gets in the way of new orgs.
    op.alter_column("organization", "encrypted_dek", nullable=False)


def downgrade() -> None:
    op.drop_column("organization", "encrypted_dek")

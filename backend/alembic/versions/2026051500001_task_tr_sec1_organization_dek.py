"""TASK-TR-SEC1: add `organization.encrypted_dek` for PII envelope encryption.

The new field-encryption path (AES-256-GCM with per-org Data Encryption
Keys, wrapped by a master KEK) requires every organization to carry a
DEK on its row. The DEK is the symmetric key used to encrypt the PII
columns that are actually written through the service layer today:
``party.gstin``, ``party.pan``, ``party.phone``,
``bank_account.account_number``, ``firm.gstin``, and
``app_user.mfa_secret``.

NOTE on ``firm.pan`` / ``firm.cin`` / ``firm.tan``: these columns exist
in the schema as ``LargeBinary`` and are intended for the same envelope
encryption, BUT no current write path populates them — signup
(``routers/auth.py``) only writes ``firm.gstin``, and there is no
firm-update endpoint yet. The audit for issue #22 confirmed zero
cleartext writes to these fields. When the firm-edit screen lands, the
service layer must thread the value through
``encrypt_pii(value, dek=dek, org_id=org_id)`` exactly like
``firm.gstin`` does — the column type is already BYTEA, so the wiring
is symmetric.

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
    # Idempotency note (issue #22 follow-up): this migration is NOT safe
    # to re-run on a database where it has already applied successfully —
    # the backfill would mint a FRESH DEK per existing org and overwrite
    # ``organization.encrypted_dek``, stranding every previously-written
    # ciphertext under the old (now-discarded) DEK. We rely on Alembic's
    # ``alembic_version`` row to ensure this `upgrade()` body runs exactly
    # once per database; the bootstrap `op.add_column(...)` would also
    # fail loud on a second invocation because the column already exists.
    # Re-keying (true rotation) is a separate, future code path with its
    # own version-byte bump — see ``app.utils.crypto.VERSION_AESGCM_V1``.

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
    # M3 review fix: downgrading would `DROP COLUMN organization.encrypted_dek`,
    # which strands every encrypted PII row in the database (party.gstin,
    # party.pan, party.phone, bank_account.account_number, app_user.mfa_secret,
    # firm.gstin, …). Each row is sealed under that org's DEK; with the DEK
    # gone, even possession of `PII_MASTER_KEY` does not recover the data.
    # The migration is forward-only by design. Roll back via a restore from
    # a pre-upgrade pg_dump backup, NOT via alembic downgrade.
    raise NotImplementedError(
        "TR-SEC1 is forward-only: dropping organization.encrypted_dek would "
        "permanently strand every encrypted PII row (per-org DEK destroyed, "
        "cannot decrypt even with PII_MASTER_KEY). To roll back, restore from "
        "a pre-upgrade backup (ops/backup.sh dumps)."
    )

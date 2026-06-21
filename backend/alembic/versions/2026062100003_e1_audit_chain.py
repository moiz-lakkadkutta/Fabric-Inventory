"""CRYPTO-01: audit-log tamper-evidence — immutable trigger + revoke UPDATE/DELETE.

Changes:
1. ``audit_log_immutable`` trigger (BEFORE UPDATE OR DELETE FOR EACH ROW) that
   unconditionally raises an exception, making audit_log effectively append-only
   at the Postgres level (on top of the application-layer invariant).
2. REVOKE UPDATE, DELETE on audit_log FROM fabric_app so the runtime role
   cannot issue those statements even without the trigger in place.

No column changes: ``prev_hash`` and ``this_hash`` already exist on
``audit_log`` (added in an earlier schema pass, NULL on existing rows).
The hash-chain logic lives entirely in ``audit_service.emit()`` — this
migration only adds the DB-level enforcement layer.

Forward-only: downgrade drops the trigger and re-grants the privileges.

Revision ID: e1_audit_chain
Revises: d1_auth_lockout
Create Date: 2026-06-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e1_audit_chain"
down_revision: str | Sequence[str] | None = "d1_auth_lockout"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Trigger function name + trigger name — kept as constants so downgrade
# is DRY and in-sync with upgrade.
_TRIGGER_FN = "audit_log_immutable_fn"
_TRIGGER_NAME = "audit_log_immutable"


def upgrade() -> None:
    # ── 1. Immutability trigger ───────────────────────────────────────────
    # Fires BEFORE every UPDATE or DELETE on audit_log (all roles, including
    # superusers — triggers are role-independent at execution time) and raises
    # an exception so the statement is aborted.  Combined with the REVOKE
    # below this gives defence-in-depth: privilege revocation stops accidental
    # mutations at the SQL level; the trigger stops deliberate ones even by
    # roles that still have the privilege (e.g. the migration role ``fabric``).
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_TRIGGER_FN}()
        RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION
                'audit_log is immutable: UPDATE and DELETE are not permitted (CRYPTO-01)';
        END;
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_TRIGGER_NAME}
            BEFORE UPDATE OR DELETE ON audit_log
            FOR EACH ROW EXECUTE FUNCTION {_TRIGGER_FN}();
        """
    )

    # ── 2. Revoke UPDATE + DELETE from fabric_app ────────────────────────
    # Guards with a DO block so the REVOKE doesn't fail in environments
    # where fabric_app doesn't exist (e.g. a fresh CI runner that hasn't
    # run the INT-9 migration yet, or a local setup using a single role).
    # Mirrors the pg_roles guard pattern from INT-9 migration.
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fabric_app') THEN
                REVOKE UPDATE, DELETE ON audit_log FROM fabric_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Re-grant first so the trigger drop doesn't leave a privilege gap.
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fabric_app') THEN
                GRANT UPDATE, DELETE ON audit_log TO fabric_app;
            END IF;
        END $$;
        """
    )
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER_NAME} ON audit_log;")
    op.execute(f"DROP FUNCTION IF EXISTS {_TRIGGER_FN}();")

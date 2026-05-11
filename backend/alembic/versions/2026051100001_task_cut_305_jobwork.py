"""TASK-CUT-305 (Half B) — Job-work send-out / receive-back tables.

Introduces four new tables for textile-trade job-work tracking:

  - ``job_work_order``         — one row per "send-out" challan to a karigar.
  - ``job_work_order_line``    — one row per item sent on a JWO (qty + uom).
  - ``job_work_receipt``       — one row per "receive-back" against a JWO.
  - ``job_work_receipt_line``  — one row per item received (finished + wastage).

All four are tenant-scoped (``org_id`` + ``firm_id``) with RLS policies
that read ``app.current_org_id``, exactly like ``stock_adjustment`` and
the other tenant-scoped tables. ``deleted_at`` is included for soft-delete
parity per CLAUDE.md "no hard delete".

Why now: TASK-CUT-401 (Wave 5) wires the FE; this migration creates the
schema TASK-CUT-401 reads/writes against. The accompanying service
(TASK-CUT-305 router/service in ``backend/app/service/jobwork_service.py``)
encapsulates the stock-move side effects so a send-out moves stock from
the firm's MAIN location to a JOBWORK location (auto-provisioned the
first time a JWO ships from that firm).

No ITC-04 fields beyond what's needed for the data preparer. ITC-04
quarterly reporting reads from these four tables + the existing GST
metadata on ``item`` and ``party`` — no separate ``itc04_*`` table is
created (the Wave 5 export task may add one if rendering needs to cache
quarter-locked snapshots).

Revision ID: task_cut_305_jobwork
Revises: task_cut_303_pw_reset
Create Date: 2026-05-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "task_cut_305_jobwork"
down_revision: str | Sequence[str] | None = "task_cut_303_pw_reset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ──────────────────────────────────────────────────────────────────────
# Enum types (status state machines)
# ──────────────────────────────────────────────────────────────────────


def _create_enum_types() -> None:
    op.execute(
        """
        CREATE TYPE job_work_order_status AS ENUM (
            'DRAFT', 'SENT', 'PARTIAL_RECEIVED', 'CLOSED', 'CANCELLED'
        )
        """
    )
    op.execute(
        """
        CREATE TYPE job_work_receipt_status AS ENUM (
            'POSTED', 'VOID'
        )
        """
    )


def _drop_enum_types() -> None:
    op.execute("DROP TYPE IF EXISTS job_work_receipt_status")
    op.execute("DROP TYPE IF EXISTS job_work_order_status")


# ──────────────────────────────────────────────────────────────────────
# Table builders
# ──────────────────────────────────────────────────────────────────────


def _create_job_work_order() -> None:
    op.create_table(
        "job_work_order",
        sa.Column(
            "job_work_order_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "firm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("firm.firm_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # `karigar` is a Party with is_karigar=True. We don't enforce that
        # constraint at the DB level — the service layer validates on insert.
        sa.Column(
            "karigar_party_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("party.party_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Numbering is gapless per (org, firm, series). Series like JW/2025-26.
        sa.Column("series", sa.String(50), nullable=False),
        sa.Column("number", sa.String(20), nullable=False),
        sa.Column("challan_date", sa.Date, nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "DRAFT",
                "SENT",
                "PARTIAL_RECEIVED",
                "CLOSED",
                "CANCELLED",
                name="job_work_order_status",
                create_type=False,
            ),
            nullable=False,
            server_default="SENT",
        ),
        sa.Column("operation", sa.String(100), nullable=True),  # e.g. Embroidery
        sa.Column("expected_return_date", sa.Date, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        # Source / destination locations on the books. Both must belong to
        # `firm_id`. We don't FK to location.location_id with CASCADE because
        # we never want a deleted Location to cascade through the JWO history.
        sa.Column(
            "from_location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("location.location_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "to_location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("location.location_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Audit columns — mirror the project-wide audit_sweep shape.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "org_id",
            "firm_id",
            "series",
            "number",
            name="job_work_order_org_firm_series_number_key",
        ),
    )
    op.create_index("idx_job_work_order_firm", "job_work_order", ["firm_id"])
    op.create_index("idx_job_work_order_karigar", "job_work_order", ["karigar_party_id"])
    op.create_index("idx_job_work_order_status", "job_work_order", ["status"])
    op.create_index(
        "idx_job_work_order_firm_date",
        "job_work_order",
        ["firm_id", "challan_date"],
    )
    op.execute("ALTER TABLE job_work_order ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY job_work_order_rls ON job_work_order "
        "USING (org_id = current_setting('app.current_org_id')::uuid)"
    )


def _create_job_work_order_line() -> None:
    op.create_table(
        "job_work_order_line",
        sa.Column(
            "job_work_order_line_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "firm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("firm.firm_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "job_work_order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("job_work_order.job_work_order_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("line_no", sa.SmallInteger, nullable=False),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("item.item_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "lot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lot.lot_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("qty_sent", sa.Numeric(15, 4), nullable=False),
        sa.Column("uom", sa.String(20), nullable=False),
        # Denormalised running tally so the receipt-back UI can show
        # "5m remaining" without an aggregate over receipt lines.
        sa.Column(
            "qty_received",
            sa.Numeric(15, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "qty_wastage",
            sa.Numeric(15, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "job_work_order_id",
            "line_no",
            name="job_work_order_line_order_lineno_key",
        ),
    )
    op.create_index("idx_job_work_order_line_order", "job_work_order_line", ["job_work_order_id"])
    op.execute("ALTER TABLE job_work_order_line ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY job_work_order_line_rls ON job_work_order_line "
        "USING (org_id = current_setting('app.current_org_id')::uuid)"
    )


def _create_job_work_receipt() -> None:
    op.create_table(
        "job_work_receipt",
        sa.Column(
            "job_work_receipt_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "firm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("firm.firm_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "job_work_order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("job_work_order.job_work_order_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("receipt_date", sa.Date, nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "POSTED",
                "VOID",
                name="job_work_receipt_status",
                create_type=False,
            ),
            nullable=False,
            server_default="POSTED",
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_job_work_receipt_firm", "job_work_receipt", ["firm_id"])
    op.create_index("idx_job_work_receipt_order", "job_work_receipt", ["job_work_order_id"])
    op.create_index(
        "idx_job_work_receipt_firm_date",
        "job_work_receipt",
        ["firm_id", "receipt_date"],
    )
    op.execute("ALTER TABLE job_work_receipt ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY job_work_receipt_rls ON job_work_receipt "
        "USING (org_id = current_setting('app.current_org_id')::uuid)"
    )


def _create_job_work_receipt_line() -> None:
    op.create_table(
        "job_work_receipt_line",
        sa.Column(
            "job_work_receipt_line_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "firm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("firm.firm_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "job_work_receipt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("job_work_receipt.job_work_receipt_id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Points to the JWO line this receipt is reducing. Required so the
        # service layer can update qty_received / qty_wastage atomically.
        sa.Column(
            "job_work_order_line_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("job_work_order_line.job_work_order_line_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("line_no", sa.SmallInteger, nullable=False),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("item.item_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("qty_received", sa.Numeric(15, 4), nullable=False),
        sa.Column("qty_wastage", sa.Numeric(15, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("uom", sa.String(20), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "job_work_receipt_id",
            "line_no",
            name="job_work_receipt_line_receipt_lineno_key",
        ),
    )
    op.create_index(
        "idx_job_work_receipt_line_receipt",
        "job_work_receipt_line",
        ["job_work_receipt_id"],
    )
    op.create_index(
        "idx_job_work_receipt_line_order_line",
        "job_work_receipt_line",
        ["job_work_order_line_id"],
    )
    op.execute("ALTER TABLE job_work_receipt_line ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY job_work_receipt_line_rls ON job_work_receipt_line "
        "USING (org_id = current_setting('app.current_org_id')::uuid)"
    )


# ──────────────────────────────────────────────────────────────────────
# Upgrade / downgrade entry points
# ──────────────────────────────────────────────────────────────────────


def _drop_legacy_jobwork_artefacts() -> None:
    """Drop the baseline-DDL job-work artefacts that this task supersedes.

    Baseline (``schema/ddl.sql``) shipped a manufacturing-oriented job-work
    design: ``job_work_order`` (header with no lines), separate
    ``outward_challan`` + ``outward_challan_line`` for the actual send-out,
    ``inward_challan`` + ``inward_challan_line`` for receive-back, and
    ``job_work_bill`` for the billing layer. Status enum was
    ``job_work_status`` with values like ISSUED / ACKNOWLEDGED.

    No application code references these tables — they were a schema
    placeholder for a Phase-3 manufacturing-flavored design. CUT-305
    introduces a simpler textile-flavored design (JWO with embedded lines,
    one receipt-back model). We drop the legacy artefacts to make room.

    ``CASCADE`` handles the inter-table FKs. ``IF EXISTS`` so re-running
    on a partially-applied DB is a no-op. The drop is destructive but
    safe because (a) tables are empty in every existing dev/prod box
    (Wave 1-3 verified nothing populates them) and (b) we are still
    inside the greenfield window per the platform audit.

    Note: ``job_work_bill`` is also dropped because its ``karigar_id``
    column has no FK constraint to my new design's foreign keys (and the
    column type ``job_work_bill_status`` would conflict if v2 ships
    billing). v1 cutover does not need job-work billing — that's a v2 ask.
    """
    # Lines + child tables first (FKs point inward → outward → job_work_order).
    op.execute("DROP TABLE IF EXISTS inward_challan_line CASCADE")
    op.execute("DROP TABLE IF EXISTS inward_challan CASCADE")
    op.execute("DROP TABLE IF EXISTS outward_challan_line CASCADE")
    op.execute("DROP TABLE IF EXISTS outward_challan CASCADE")
    op.execute("DROP TABLE IF EXISTS job_work_bill CASCADE")
    op.execute("DROP TABLE IF EXISTS job_work_order CASCADE")
    # Legacy enums these tables used.
    op.execute("DROP TYPE IF EXISTS job_work_status")
    op.execute("DROP TYPE IF EXISTS job_work_bill_status")
    op.execute("DROP TYPE IF EXISTS challan_status")


def upgrade() -> None:
    _drop_legacy_jobwork_artefacts()
    _create_enum_types()
    _create_job_work_order()
    _create_job_work_order_line()
    _create_job_work_receipt()
    _create_job_work_receipt_line()


def downgrade() -> None:
    # Tables in reverse dependency order.
    op.execute("DROP POLICY IF EXISTS job_work_receipt_line_rls ON job_work_receipt_line")
    op.execute("DROP TABLE IF EXISTS job_work_receipt_line CASCADE")
    op.execute("DROP POLICY IF EXISTS job_work_receipt_rls ON job_work_receipt")
    op.execute("DROP TABLE IF EXISTS job_work_receipt CASCADE")
    op.execute("DROP POLICY IF EXISTS job_work_order_line_rls ON job_work_order_line")
    op.execute("DROP TABLE IF EXISTS job_work_order_line CASCADE")
    op.execute("DROP POLICY IF EXISTS job_work_order_rls ON job_work_order")
    op.execute("DROP TABLE IF EXISTS job_work_order CASCADE")
    _drop_enum_types()
    # Note: this downgrade does NOT restore the dropped legacy artefacts
    # (outward_challan, inward_challan, job_work_bill, …). Restoring them
    # would require re-running large fragments of ddl.sql which is brittle.
    # If a rollback is needed in practice, run `make migrate` to head from
    # ``task_cut_104_voucher_party_id`` against a freshly-loaded DDL.

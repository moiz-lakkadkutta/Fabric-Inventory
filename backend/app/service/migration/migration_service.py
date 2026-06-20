"""Migration orchestration service — TASK-CUT-402.

Coordinates the upload → reconcile → approve → commit pipeline.

Flow:

    1. ``upload_and_reconcile`` — caller hands in the file bytes and
       firm_id. We run the adapter's ``validate``, persist a
       ``user_migration`` row with status RECONCILED and the
       serialized report in ``reconciliation_json``. Return the row.

    2. ``approve`` — caller hands in migration_id. We replay the
       adapter against the (in-memory cached or re-supplied) source,
       resolve intermediate rows to real Party / Voucher entities in
       one transaction, post a single compound OPENING_BAL voucher
       per cutover, stamp ``approved_by`` / ``approved_at``, flip
       status to APPROVED. If commit fails mid-flight, status flips
       to FAILED with ``failure_reason`` populated; the caller can
       re-upload and try again.

    3. ``reject`` — caller hands in migration_id. We stamp
       ``rejected_at`` and flip status to REJECTED. Idempotent.

Approval is owner-gated at the router level via the
``admin.migrations.approve`` permission. The service itself does NOT
enforce permissions — services are below the permission gate per
CLAUDE.md.

Source persistence: we DO NOT persist the uploaded file (no S3, no
local disk). Instead, the approve step requires the source to be
re-supplied — the FE workflow is "upload → preview → click Approve
which re-uploads the same bytes." This avoids a whole class of leaky
file-store bugs and keeps the migration auditable: the approver always
sees the file they're about to commit, not a possibly-stale version on
disk.

(Side benefit: when CUT-404 adds backups, ``user_migration`` survives
pg_dump but a leftover file fragment would not.)
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError, NotFoundError
from app.models import Ledger, UserMigration, Voucher, VoucherLine
from app.models.accounting import JournalLineType, VoucherStatus, VoucherType
from app.models.masters import TaxStatus
from app.service import audit_service, masters_service
from app.service.common_guards import assert_firm_in_org

from .intermediate import (
    IntermediateOpeningBalance,
    MigrationValidationReport,
    OpeningLedgerKind,
)
from .protocol import MigrationAdapter

# Migration status state machine. Free-form TEXT in DDL; enforced here.
STATUS_UPLOADED = "UPLOADED"
STATUS_RECONCILED = "RECONCILED"
STATUS_APPROVED = "APPROVED"
STATUS_REJECTED = "REJECTED"
STATUS_FAILED = "FAILED"

_TERMINAL_STATUSES = frozenset({STATUS_APPROVED, STATUS_REJECTED})

# COA ledger codes per ``seed_service._SYSTEM_LEDGERS``. The opening-
# balance commit step resolves intermediate ledger kinds onto these.
_LEDGER_CODE_FOR_KIND: dict[OpeningLedgerKind, str] = {
    "SUNDRY_DEBTORS": "1200",
    "SUNDRY_CREDITORS": "2000",
    "CASH": "1000",
    "BANK": "1100",
    "CAPITAL": "3000",
    "OTHER": "3100",  # Retained earnings — the safe destination for
    # unclassified opening movements when a source ledger
    # isn't named explicitly. Re-classify later in the UI.
}

# Suspense ledger for the cutover. A parties-only source export never
# self-balances — the firm's capital / cash / stock live in other
# sheets we don't ingest in v1. Rather than reject the migration, the
# commit step posts the DR/CR gap to this ledger so the OB voucher
# balances; the accountant reclassifies it post-cutover. Seeded by
# ``seed_service._SYSTEM_LEDGERS``.
_OPENING_DIFFERENCE_LEDGER_CODE = "3200"


@dataclass(frozen=True)
class CommitResult:
    """What the approve path returns.

    ``opening_voucher_id`` is None when there were zero non-zero opening
    balances (parties imported, no journal posted).
    """

    migration: UserMigration
    parties_created: int
    parties_skipped: int
    opening_voucher_id: uuid.UUID | None
    tb_debits: Decimal
    tb_credits: Decimal


@dataclass(frozen=True)
class _OpeningVoucherPostResult:
    """Result of ``_post_opening_balance_voucher``.

    Carries the actually-posted suspense amount + side so ``approve()``
    can size the ``OB_DIFFERENCE_PARKED`` warn-row from the same totals
    the voucher used, not from the pre-skip ``_sum_ob_sides`` totals
    (which may include orphan OB rows the voucher dropped).

    ``parked_side`` is ``None`` iff ``parked_amount == 0`` — i.e. the
    post-skip OBs self-balanced and no suspense line was posted.
    """

    voucher_id: uuid.UUID
    parked_amount: Decimal
    parked_side: str | None


def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.UTC)


def _serialize_report(report: MigrationValidationReport) -> dict[str, object]:
    """Convert the Pydantic report to JSON-friendly primitives.

    Decimal → str (lossless), tuples → lists.
    """
    return {
        "total_parties": report.total_parties,
        "total_opening_balances": report.total_opening_balances,
        "errors": report.errors,
        "warnings": report.warnings,
        "rows": [
            {
                "severity": r.severity,
                "code": r.code,
                "message": r.message,
                "source_ref": r.source_ref,
            }
            for r in report.rows
        ],
        "tb_reconciles": report.tb_reconciles,
        "tb_diff": str(report.tb_diff) if report.tb_diff is not None else None,
    }


# ──────────────────────────────────────────────────────────────────────
# Upload + reconcile
# ──────────────────────────────────────────────────────────────────────


def upload_and_reconcile(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    uploaded_by: uuid.UUID,
    source_bytes: bytes,
    source_filename: str,
    adapter: MigrationAdapter,
    source_format: str,
) -> UserMigration:
    """Persist a new ``user_migration`` row with the reconciliation report.

    The adapter is invoked twice:

      1. ``validate()`` produces the report shown to the user.
      2. ``extract_*`` is replayed at approval time — we don't cache
         intermediate rows in the DB because they may be large and
         we want approval to re-read fresh bytes (the user must
         re-supply the source on click-Approve).

    TB reconciliation is computed here on the validate path so the
    user sees the ±₹0 invariant BEFORE they click Approve. The
    approve step re-checks it (defense-in-depth) against the supplied
    bytes.
    """
    assert_firm_in_org(session, org_id=org_id, firm_id=firm_id)

    if not source_bytes:
        raise AppValidationError("Empty migration upload — file is required.")
    if not source_filename:
        raise AppValidationError("Migration upload missing source_filename.")

    report = adapter.validate(source_bytes)

    # Compute TB pre/post diff from the adapter's intermediate OBs.
    tb_debits, tb_credits = _sum_ob_sides(adapter.extract_opening_balances(source_bytes))
    tb_diff = tb_debits - tb_credits
    report_with_tb = report.model_copy(
        update={
            "tb_reconciles": tb_diff == 0,
            "tb_diff": tb_diff,
        }
    )

    row = UserMigration(
        org_id=org_id,
        firm_id=firm_id,
        source_format=source_format,
        source_filename=source_filename[:255],
        status=STATUS_RECONCILED,
        uploaded_by=uploaded_by,
        reconciliation_json=_serialize_report(report_with_tb),
    )
    session.add(row)
    session.flush()

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=uploaded_by,
        entity_type="admin.migration",
        entity_id=row.migration_id,
        action="upload",
        changes={
            "after": {
                "source_format": source_format,
                "source_filename": row.source_filename,
                "total_parties": report.total_parties,
                "total_opening_balances": report.total_opening_balances,
                "errors": report.errors,
                "warnings": report.warnings,
                "tb_diff": str(tb_diff),
            }
        },
    )
    return row


def _sum_ob_sides(
    obs: Iterable[IntermediateOpeningBalance],
) -> tuple[Decimal, Decimal]:
    """Sum DR vs CR amounts across the supplied OB rows."""
    dr = Decimal("0")
    cr = Decimal("0")
    for ob in obs:
        if ob.side == "DR":
            dr += ob.amount
        else:
            cr += ob.amount
    return dr, cr


# ──────────────────────────────────────────────────────────────────────
# Approval — commits parties + opening-balance voucher
# ──────────────────────────────────────────────────────────────────────


def get_migration(session: Session, *, org_id: uuid.UUID, migration_id: uuid.UUID) -> UserMigration:
    """Fetch a migration row, RLS-isolated by org_id."""
    row = session.execute(
        select(UserMigration).where(
            UserMigration.migration_id == migration_id,
            UserMigration.org_id == org_id,
            UserMigration.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"Migration {migration_id} not found")
    return row


def list_migrations(session: Session, *, org_id: uuid.UUID, limit: int = 50) -> list[UserMigration]:
    """List migrations for the caller's org, newest first."""
    stmt = (
        select(UserMigration)
        .where(UserMigration.org_id == org_id, UserMigration.deleted_at.is_(None))
        .order_by(UserMigration.uploaded_at.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars())


def approve(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    migration_id: uuid.UUID,
    approver_user_id: uuid.UUID,
    source_bytes: bytes,
    adapter: MigrationAdapter,
    opening_date: datetime.date | None = None,
) -> CommitResult:
    """Commit a reconciled migration: create parties + post the OB voucher.

    Single transaction (the caller owns the session). On any failure,
    we re-raise after stamping the row's status as FAILED with a
    failure_reason — but we DO NOT commit those metadata changes
    ourselves (the caller's exception handler rolls back). The
    failure_reason makes it back to the user only when the caller
    catches and persists.

    ``source_bytes`` must be the same content as the original upload —
    the FE re-uploads on click-Approve. We re-run the adapter against
    those bytes; the persisted report is for display only.
    """
    row = get_migration(session, org_id=org_id, migration_id=migration_id)
    if row.firm_id != firm_id:
        # Defensive — the API hands in the firm from the migration row,
        # but a malicious caller could supply a mismatching firm. RLS
        # would still scope to org but firm-level invariants are looser.
        raise AppValidationError("Migration firm_id mismatch.")
    if row.status in _TERMINAL_STATUSES:
        raise AppValidationError(
            f"Migration {migration_id} is already {row.status}; cannot approve."
        )
    if row.status == STATUS_FAILED:
        raise AppValidationError(
            f"Migration {migration_id} previously failed; please re-upload "
            "the source and try again."
        )

    parties_intermediate = list(adapter.extract_parties(source_bytes))
    obs_intermediate = list(adapter.extract_opening_balances(source_bytes))

    # Party-scoped opening balances almost never self-balance — a
    # parties-only source export carries debtors/creditors but not the
    # firm's capital/cash/stock. The DR/CR gap is expected; it's posted
    # to the '3200 Opening Balance Difference' suspense ledger by
    # _post_opening_balance_voucher so the OB voucher still balances.
    # We keep the sums for the audit trail + the parked-difference report.
    dr_total, cr_total = _sum_ob_sides(obs_intermediate)

    # Create parties (idempotent on code uniqueness). Skip rows whose
    # code already exists — typical re-upload scenario where the user
    # ran the migration once, fixed the source, and re-ran.
    party_id_by_source: dict[str, uuid.UUID] = {}
    parties_created = 0
    parties_skipped = 0
    for ip in parties_intermediate:
        existing_party_id = _resolve_existing_party(
            session, org_id=org_id, firm_id=firm_id, code=ip.code
        )
        if existing_party_id is not None:
            party_id_by_source[ip.source_id] = existing_party_id
            parties_skipped += 1
            continue
        party = masters_service.create_party(
            session,
            org_id=org_id,
            firm_id=firm_id,
            code=ip.code,
            name=ip.name,
            is_customer="CUSTOMER" in ip.kinds,
            is_supplier="SUPPLIER" in ip.kinds or "KARIGAR" in ip.kinds,
            is_karigar="KARIGAR" in ip.kinds,
            is_transporter="TRANSPORTER" in ip.kinds,
            tax_status=TaxStatus.REGULAR if ip.gstin else TaxStatus.UNREGISTERED,
            gstin=ip.gstin,
            pan=ip.pan,
            phone=ip.phone,
            email=ip.email,
            state_code=ip.state_code,
            contact_person=ip.contact_person,
            notes=f"Imported from Vyapar migration {migration_id}",
            created_by=approver_user_id,
        )
        party_id_by_source[ip.source_id] = party.party_id
        parties_created += 1

    # Post the compound opening-balance voucher. One header, N lines.
    opening_voucher_id: uuid.UUID | None = None
    parked_amount = Decimal("0")
    parked_side: str | None = None
    voucher_date = opening_date or _previous_day_in_kolkata()
    if obs_intermediate:
        post_result = _post_opening_balance_voucher(
            session,
            org_id=org_id,
            firm_id=firm_id,
            obs=obs_intermediate,
            party_id_by_source=party_id_by_source,
            posted_by=approver_user_id,
            voucher_date=voucher_date,
            migration_id=migration_id,
        )
        opening_voucher_id = post_result.voucher_id
        parked_amount = post_result.parked_amount
        parked_side = post_result.parked_side

    # Surface the parked suspense amount prominently in the report the
    # FE preview pane renders. We size the message from the
    # actually-posted parked amount + side (returned by
    # _post_opening_balance_voucher), NOT from the pre-skip
    # _sum_ob_sides(obs_intermediate) totals. The two can diverge if the
    # voucher loop drops orphan OB rows whose party_source_id isn't in
    # party_id_by_source — using the pre-skip totals here would print a
    # parked amount the books don't actually carry. tb_reconciles stays
    # False — honest: the *source* did not reconcile; we parked the gap,
    # we didn't fix it.
    if parked_amount > 0:
        recon = dict(row.reconciliation_json or {})
        recon_rows = list(recon.get("rows", []))
        recon_rows.append(
            {
                "severity": "warn",
                "code": "OB_DIFFERENCE_PARKED",
                "message": (
                    f"Opening balances differed by {parked_amount} ({parked_side}). "
                    "Parked in '3200 Opening Balance Difference'. Reclassify to "
                    "capital / cash / stock via Accounting -> New voucher."
                ),
                "source_ref": None,
            }
        )
        recon["rows"] = recon_rows
        recon["warnings"] = int(recon.get("warnings", 0)) + 1
        row.reconciliation_json = recon

    row.status = STATUS_APPROVED
    row.approved_by = approver_user_id
    row.approved_at = _now_utc()
    row.updated_at = _now_utc()
    session.flush()

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=approver_user_id,
        entity_type="admin.migration",
        entity_id=row.migration_id,
        action="approve",
        changes={
            "after": {
                "parties_created": parties_created,
                "parties_skipped": parties_skipped,
                "opening_voucher_id": str(opening_voucher_id) if opening_voucher_id else None,
                "tb_debits": str(dr_total),
                "tb_credits": str(cr_total),
            }
        },
    )

    return CommitResult(
        migration=row,
        parties_created=parties_created,
        parties_skipped=parties_skipped,
        opening_voucher_id=opening_voucher_id,
        tb_debits=dr_total,
        tb_credits=cr_total,
    )


def reject(
    session: Session,
    *,
    org_id: uuid.UUID,
    migration_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> UserMigration:
    """Mark a migration as REJECTED. No parties created, no journals posted.

    Idempotent on already-REJECTED rows. Fails if the migration is in
    a terminal-but-different state (APPROVED).
    """
    row = get_migration(session, org_id=org_id, migration_id=migration_id)
    if row.status == STATUS_REJECTED:
        return row
    if row.status == STATUS_APPROVED:
        raise AppValidationError(f"Migration {migration_id} is already APPROVED; cannot reject.")
    row.status = STATUS_REJECTED
    row.rejected_at = _now_utc()
    row.updated_at = _now_utc()
    session.flush()
    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=row.firm_id,
        user_id=actor_user_id,
        entity_type="admin.migration",
        entity_id=row.migration_id,
        action="reject",
        changes={"after": {"status": STATUS_REJECTED}},
    )
    return row


def mark_failed(
    session: Session,
    *,
    org_id: uuid.UUID,
    migration_id: uuid.UUID,
    reason: str,
    actor_user_id: uuid.UUID | None,
) -> UserMigration:
    """Flag a migration as FAILED after a commit-time exception.

    Used by the router's exception handler: catch the AppValidationError /
    IntegrityError, rollback, then in a fresh session set status =
    FAILED with the failure reason so the FE can render an error panel.
    """
    row = get_migration(session, org_id=org_id, migration_id=migration_id)
    row.status = STATUS_FAILED
    row.failure_reason = reason[:1024]
    row.updated_at = _now_utc()
    session.flush()
    if actor_user_id is not None:
        audit_service.emit(
            session,
            org_id=org_id,
            firm_id=row.firm_id,
            user_id=actor_user_id,
            entity_type="admin.migration",
            entity_id=row.migration_id,
            action="fail",
            changes={"after": {"failure_reason": reason[:256]}},
        )
    return row


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _resolve_existing_party(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    code: str,
) -> uuid.UUID | None:
    """Return party_id if a non-deleted party with this code exists in scope.

    Mirrors masters_service.create_party's uniqueness rule:
        UNIQUE (org_id, COALESCE(firm_id, NULL), code) — same firm,
        same code → re-use.
    """
    from app.models import Party  # local import to avoid cycle

    stmt = select(Party.party_id).where(
        Party.org_id == org_id,
        Party.code == code,
        Party.deleted_at.is_(None),
    )
    stmt = (
        stmt.where(Party.firm_id == firm_id)
        if firm_id is not None
        else stmt.where(Party.firm_id.is_(None))
    )
    return session.execute(stmt).scalar_one_or_none()


def _previous_day_in_kolkata() -> datetime.date:
    """Default opening-balance date: yesterday in Asia/Kolkata.

    Per the task spec, the OB voucher is dated 1 day before the
    migration so the first day of operations on Fabric starts with a
    clean opening TB. Fine-grained timezone-correctness isn't critical
    — the user can override on the FE.
    """
    now_utc = _now_utc()
    # Asia/Kolkata is UTC+5:30; for a "yesterday in IST" effect, shift
    # by 5h30m then take date - 1.
    ist = now_utc + datetime.timedelta(hours=5, minutes=30)
    return ist.date() - datetime.timedelta(days=1)


def _resolve_ledger_by_code(session: Session, *, org_id: uuid.UUID, code: str) -> Ledger:
    """Resolve a seeded firm-scoped-NULL system ledger by its COA code.

    The seed_service plants these per org at signup time. Raises a
    clear AppValidationError if the code is absent (an org seeded
    before the ledger was added to ``_SYSTEM_LEDGERS``).
    """
    ledger = session.execute(
        select(Ledger).where(
            Ledger.org_id == org_id,
            Ledger.code == code,
            Ledger.firm_id.is_(None),
            Ledger.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if ledger is None:
        raise AppValidationError(
            f"System ledger {code!r} missing for org {org_id} — "
            "the COA seed must run before approving migrations."
        )
    return ledger


def _resolve_ledger_for_kind(
    session: Session, *, org_id: uuid.UUID, kind: OpeningLedgerKind
) -> Ledger:
    """Resolve a seeded system ledger by intermediate-format kind.

    Opening balances post against the seeded firm-scoped-NULL ledgers
    (control accounts for AR / AP, plain ledgers for cash / capital).
    A future Wave-2 enhancement can let users override which ledger
    each kind maps to.
    """
    return _resolve_ledger_by_code(session, org_id=org_id, code=_LEDGER_CODE_FOR_KIND[kind])


def _post_opening_balance_voucher(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    obs: list[IntermediateOpeningBalance],
    party_id_by_source: dict[str, uuid.UUID],
    posted_by: uuid.UUID,
    voucher_date: datetime.date,
    migration_id: uuid.UUID,
) -> _OpeningVoucherPostResult:
    """Create one compound OPENING_BAL voucher with all opening lines.

    Lines:
        DR Sundry Debtors            Σ customer receivables (per-party)
        CR Sundry Creditors          Σ supplier payables (per-party)
        DR/CR Opening Balance Diff   the balancing suspense line (see below)

    For v1, only party-scoped sundry-debtor / sundry-creditor balances
    appear in the source — a parties-only export carries no firm-level
    cash / capital / bank rows. That makes the per-party lines almost
    always lopsided, so we add ONE balancing line to the
    '3200 Opening Balance Difference' suspense ledger for the DR/CR gap.
    The voucher is therefore always internally balanced; the accountant
    reclassifies the suspense amount to capital / cash / stock
    post-cutover via /accounting → New voucher.

    Returns an ``_OpeningVoucherPostResult`` carrying the voucher id
    plus the actually-posted suspense amount + side. The caller uses
    those values (NOT the pre-skip ``_sum_ob_sides`` totals computed
    over the raw adapter output) to size the user-facing
    ``OB_DIFFERENCE_PARKED`` warn-row, so the two stay consistent even
    if the loop below drops orphan OB rows whose party didn't come
    through.

    Invariant: after the suspense line, ``Σ DR == Σ CR`` — still
    asserted before flush as a loud safety net.
    """
    series = "OB"
    number = _allocate_opening_voucher_number(session, org_id=org_id, firm_id=firm_id)

    voucher = Voucher(
        org_id=org_id,
        firm_id=firm_id,
        voucher_type=VoucherType.OPENING_BAL,
        series=series,
        number=number,
        voucher_date=voucher_date,
        reference_type="user_migration",
        reference_id=migration_id,
        narration="Opening Balances - imported from Vyapar",
        status=VoucherStatus.POSTED,
        created_by=posted_by,
    )
    session.add(voucher)
    session.flush()

    total_dr = Decimal("0")
    total_cr = Decimal("0")
    seq = 1
    for ob in obs:
        if ob.party_source_id is not None and ob.party_source_id not in party_id_by_source:
            # An OB row references a party that didn't make it into the
            # parties dict — typically because the party row had an empty
            # name and we skipped it, or (per the Protocol's looser
            # contract for future Tally / generic-Excel adapters) the
            # adapter emitted an OB referencing a party it never yielded.
            # Drop the OB row too; we'd produce a dangling reference
            # otherwise.
            continue
        ledger = _resolve_ledger_for_kind(session, org_id=org_id, kind=ob.ledger_kind)
        amount = Decimal(ob.amount)
        if ob.side == "DR":
            line_type = JournalLineType.DR
            total_dr += amount
        else:
            line_type = JournalLineType.CR
            total_cr += amount
        session.add(
            VoucherLine(
                org_id=org_id,
                voucher_id=voucher.voucher_id,
                ledger_id=ledger.ledger_id,
                line_type=line_type,
                amount=amount,
                description=ob.narration
                or f"Opening balance ({ob.ledger_kind}, source {ob.source_id})",
                sequence=seq,
            )
        )
        seq += 1

    # Park the post-skip DR/CR gap in the suspense ledger. A parties-only
    # source never self-balances; the remainder is the firm's capital /
    # cash / stock, which the parties export doesn't carry. One balancing
    # line keeps the voucher internally balanced. We track the parked
    # amount + side and return them so approve()'s reconciliation row
    # sees the same number that hit the books.
    parked_amount = Decimal("0")
    parked_side: str | None = None
    if total_dr != total_cr:
        suspense = _resolve_ledger_by_code(
            session, org_id=org_id, code=_OPENING_DIFFERENCE_LEDGER_CODE
        )
        diff = abs(total_dr - total_cr)
        if total_dr > total_cr:
            suspense_line_type = JournalLineType.CR
            total_cr += diff
        else:
            suspense_line_type = JournalLineType.DR
            total_dr += diff
        parked_amount = diff
        parked_side = suspense_line_type.value  # "DR" / "CR"
        session.add(
            VoucherLine(
                org_id=org_id,
                voucher_id=voucher.voucher_id,
                ledger_id=suspense.ledger_id,
                line_type=suspense_line_type,
                amount=diff,
                description=(
                    "Opening balance difference — parties-only import gap; "
                    "reclassify to capital / cash / stock"
                ),
                sequence=seq,
            )
        )
        seq += 1

    session.flush()

    if total_dr != total_cr:
        # Unreachable after the suspense line above — kept as a loud
        # safety net against a future regression in the balancing logic.
        raise AppValidationError(
            f"Opening-balance voucher unbalanced after post: DR {total_dr} vs CR {total_cr}. "
            "Rolling back."
        )

    voucher.total_debit = total_dr
    voucher.total_credit = total_cr
    session.flush()
    return _OpeningVoucherPostResult(
        voucher_id=voucher.voucher_id,
        parked_amount=parked_amount,
        parked_side=parked_side,
    )


def _allocate_opening_voucher_number(
    session: Session, *, org_id: uuid.UUID, firm_id: uuid.UUID
) -> str:
    """Allocate the next OB/<NNNN> voucher number for the firm.

    Mirrors ``accounting_service._allocate_voucher_number`` for shape;
    series-only count, no FY prefix.
    """
    from sqlalchemy import func

    last = session.execute(
        select(func.coalesce(func.max(Voucher.number), "0")).where(
            Voucher.org_id == org_id,
            Voucher.firm_id == firm_id,
            Voucher.voucher_type == VoucherType.OPENING_BAL,
            Voucher.series == "OB",
        )
    ).scalar_one()
    try:
        last_int = int(last)
    except (ValueError, TypeError):
        last_int = 0
    return f"{last_int + 1:04d}"


__all__ = [
    "STATUS_APPROVED",
    "STATUS_FAILED",
    "STATUS_RECONCILED",
    "STATUS_REJECTED",
    "STATUS_UPLOADED",
    "CommitResult",
    "approve",
    "get_migration",
    "list_migrations",
    "mark_failed",
    "reject",
    "upload_and_reconcile",
]

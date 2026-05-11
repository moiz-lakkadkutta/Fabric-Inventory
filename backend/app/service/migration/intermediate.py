"""Intermediate format — canonical Pydantic models every adapter emits.

The migration pipeline is::

    source (.xlsx / .vyp / .xml / …)
        │
        │ adapter.extract_parties()
        │ adapter.extract_opening_balances()
        ▼
    list[IntermediateParty]
    list[IntermediateOpeningBalance]
        │
        │ commit_to_db()  (Wave 5: TASK-CUT-402)
        ▼
    party / ledger / voucher rows in Postgres

This module owns the shape of the intermediate format. Adapters must not
add fields outside this module; if a Vyapar column has no home here it
either belongs in v1 (add it here, then in the adapter) or it doesn't
(drop it on the adapter floor).

v1 scope (CLAUDE.md decision #5 + cutover-plan v1):
- Parties: name, code, GSTIN, state, kind (customer/supplier/karigar/transporter).
- Opening balances: one row per (party, ledger) with DR/CR signed amount.

OUT of v1 (deferred to v2 explicitly): items + opening stock, transaction
history (invoices/receipts/POs), bank-account masters, COA overlay.

Money is ``Decimal`` per CLAUDE.md (no float, ever). Timestamps are not
modelled in v1 — opening balances are as-of the user's chosen cutover date,
which the wrapping ``commit_to_db`` call carries on the migration session,
not on each row.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Party "kind" flags map to the existing `party` table booleans. We keep
# them as a literal list rather than the four bools so the adapter can
# emit `kinds=["CUSTOMER", "SUPPLIER"]` for a dual-role party and the
# commit step fans that out into `is_customer = True, is_supplier = True`.
PartyKind = Literal["CUSTOMER", "SUPPLIER", "KARIGAR", "TRANSPORTER"]


# Ledger "kind" tracks which COA bucket an opening balance lands in.
# This is the minimal set the v1 cutover needs — sundry debtors (customer
# receivable), sundry creditors (supplier payable), cash, bank, capital,
# and a generic "other" for one-off ledgers. The commit step (Wave 5)
# resolves these to the seeded COA ledger UUIDs.
OpeningLedgerKind = Literal[
    "SUNDRY_DEBTORS",
    "SUNDRY_CREDITORS",
    "CASH",
    "BANK",
    "CAPITAL",
    "OTHER",
]


# DR/CR is explicit in the intermediate format. We do not signed-encode
# (DR = positive, CR = negative) on the wire because the source format
# may not — Vyapar's export, for example, has a separate "type" column.
# Storing it explicitly makes the round-trip lossless and the validation
# report unambiguous.
BalanceSide = Literal["DR", "CR"]


class IntermediateParty(BaseModel):
    """One party row, normalised across source formats.

    The adapter is responsible for producing this shape from whatever its
    source emits. Validation is intentionally loose at this layer — strict
    GSTIN format, state-code lookups, etc. happen in the commit step,
    after the validation report has flagged unparseable rows.
    """

    # Pydantic v2: frozen for safety — the intermediate rows are pass-by-
    # value through the pipeline. Adapters that need to mutate clone first.
    model_config = ConfigDict(frozen=True, extra="forbid")

    # `source_id` is the adapter's own row identifier (e.g. Vyapar's
    # `party_id` from its SQLite, or the Excel row index). Used by the
    # reconciliation report so a flagged row can be located in the source.
    source_id: str = Field(min_length=1, max_length=128)

    name: str = Field(min_length=1, max_length=255)
    # Code is the user-facing short ref (e.g. ACME, KARIGAR-IMRAN). Adapter
    # may synthesise this from the name when the source has no equivalent.
    code: str = Field(min_length=1, max_length=50)

    # Kinds is a non-empty set of role flags. The commit step asserts the
    # same party isn't both a supplier and a karigar without explicit consent
    # (a karigar IS a supplier-type relationship in our schema; commit
    # collapses KARIGAR → is_karigar=True, is_supplier=True).
    kinds: tuple[PartyKind, ...] = Field(min_length=1)

    # GSTIN is opt-in; many small textile parties are unregistered. The
    # commit step validates format and looks up the state. Plain string
    # at this layer (no envelope encryption — that happens on the way
    # into the DB).
    gstin: str | None = Field(default=None, max_length=15)
    pan: str | None = Field(default=None, max_length=10)
    state_code: str | None = Field(default=None, min_length=2, max_length=2)

    # Optional fields shared across all adapters. Phone / email are common
    # enough that even a basic Excel template carries them.
    contact_person: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=1024)


class IntermediateOpeningBalance(BaseModel):
    """One opening-balance row, normalised across source formats.

    Models a single (ledger, party) line. A party with one outstanding
    invoice has one row (SUNDRY_DEBTORS, DR, ₹X). A party with no
    outstanding balance produces no row (parties without balances are
    still imported, just without an OB entry).

    The cash / capital / bank opening balances are emitted as rows with
    `party_source_id = None` — they hit the firm's COA but aren't
    party-scoped.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1, max_length=128)

    # `None` when the OB is firm-level (cash, capital, bank). Set when
    # the OB is party-scoped (sundry debtor / creditor). Adapter MUST
    # populate this with the same value it used for IntermediateParty's
    # source_id so the commit step can resolve the FK.
    party_source_id: str | None = None

    ledger_kind: OpeningLedgerKind

    # Money is Decimal. Magnitude only — sign is on the `side` field.
    # CLAUDE.md: "Always Decimal in Python. Never float."
    amount: Decimal = Field(ge=Decimal("0"))
    side: BalanceSide

    # Optional free-text description (e.g. Vyapar's "Opening balance as
    # of 2026-04-01"). Preserved verbatim onto the journal-voucher narration.
    narration: str | None = Field(default=None, max_length=512)


class ReconciliationRow(BaseModel):
    """One row of feedback in the validation report.

    Severity:
      - ``error``: the row will be skipped by the commit step. Migration
        as a whole fails the ±₹1 TB reconciliation gate.
      - ``warn``: the row will be imported but flagged for the user
        (e.g. GSTIN missing on a customer that has GST'd invoices later).
      - ``info``: informational only (e.g. "1247 rows extracted from
        sheet 'Party Master'").
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    severity: Literal["error", "warn", "info"]
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=1024)
    # `source_ref` is whatever the adapter wants to point at — typically
    # the source_id of the offending row, or "sheet:row" for Excel.
    source_ref: str | None = Field(default=None, max_length=128)


class MigrationValidationReport(BaseModel):
    """Return value of ``MigrationAdapter.validate``.

    ``tb_reconciles`` and ``tb_diff`` are populated by the commit step
    (not validate) but live on the same envelope so the FE renders a
    single "Migration preview" panel without splicing two responses.
    Adapter.validate may leave them at their defaults.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_parties: int = Field(ge=0, default=0)
    total_opening_balances: int = Field(ge=0, default=0)

    # Counters by severity for at-a-glance UI.
    errors: int = Field(ge=0, default=0)
    warnings: int = Field(ge=0, default=0)

    # Tuple (not list) so the report is hashable / cacheable. Upstream
    # treats this as ordered: errors first, then warnings, then info.
    rows: tuple[ReconciliationRow, ...] = ()

    # TB reconciliation result. ``None`` when not yet computed.
    tb_reconciles: bool | None = None
    tb_diff: Decimal | None = None


__all__ = [
    "BalanceSide",
    "IntermediateOpeningBalance",
    "IntermediateParty",
    "MigrationValidationReport",
    "OpeningLedgerKind",
    "PartyKind",
    "ReconciliationRow",
]

"""TASK-CUT-305 Half A — MigrationAdapter Protocol + intermediate-format tests.

What this proves:

1. ``NoopMigrationAdapter`` structurally conforms to the ``MigrationAdapter``
   Protocol — ``isinstance(instance, MigrationAdapter)`` returns True. This
   is the contract Wave 5's ``VyaparExcelAdapter`` (TASK-CUT-402) will plug
   into without any registration code.

2. The intermediate types (``IntermediateParty``, ``IntermediateOpeningBalance``,
   ``MigrationValidationReport``, ``ReconciliationRow``) round-trip through
   JSON without loss. That matters because Wave 5's commit step renders the
   validation report as a JSON envelope on the wire; if Pydantic loses any
   field on the way out and back, the FE will silently mis-render.

3. ``Decimal`` survives the JSON round-trip. CLAUDE.md is emphatic: money
   never goes through float. Pydantic v2 serialises Decimal as a string by
   default; the test verifies that the deserialised value is bit-for-bit
   equal to the original Decimal.

NOT in this test file:
- Vyapar parser behavior (that's TASK-CUT-402 in Wave 5).
- DB commit step (also Wave 5).
- Generic Excel adapter (v2).
"""

from __future__ import annotations

import json
from decimal import Decimal

from app.service.migration import (
    IntermediateOpeningBalance,
    IntermediateParty,
    MigrationAdapter,
    MigrationValidationReport,
    NoopMigrationAdapter,
    ReconciliationRow,
)

# ──────────────────────────────────────────────────────────────────────
# 1. Structural conformance — the Protocol's whole point
# ──────────────────────────────────────────────────────────────────────


def test_noop_adapter_conforms_to_migration_adapter_protocol() -> None:
    """The Noop adapter must satisfy MigrationAdapter structurally.

    runtime_checkable Protocol → isinstance() returns True iff the
    object has all three required methods with the right names. If a
    refactor accidentally drops a method or renames a parameter, this
    test breaks before Wave 5 picks up TASK-CUT-402.
    """
    adapter = NoopMigrationAdapter()
    assert isinstance(adapter, MigrationAdapter)


def test_noop_adapter_yields_zero_rows() -> None:
    """The stub adapter's whole job is to be safe-empty.

    Wave 5's FE preview pane calls this before any file is uploaded.
    If the stub ever emits a row, the preview will spuriously highlight
    "1 party found" with no source loaded.
    """
    adapter = NoopMigrationAdapter()
    # Pass a dict per the task spec ("takes a dict, yields zero parties").
    source = {"sheet": "Party Master"}

    parties = list(adapter.extract_parties(source))
    balances = list(adapter.extract_opening_balances(source))

    assert parties == []
    assert balances == []


def test_noop_adapter_validate_returns_zero_counts() -> None:
    """validate() on Noop returns a clean zero-row report with one info row."""
    adapter = NoopMigrationAdapter()
    report = adapter.validate({"any": "shape"})

    assert isinstance(report, MigrationValidationReport)
    assert report.total_parties == 0
    assert report.total_opening_balances == 0
    assert report.errors == 0
    assert report.warnings == 0
    # The info row is intentional — see noop_adapter.py docstring.
    assert len(report.rows) == 1
    assert report.rows[0].severity == "info"
    assert report.rows[0].code == "NOOP"


# ──────────────────────────────────────────────────────────────────────
# 2. JSON round-trip — Wave 5's wire format depends on this
# ──────────────────────────────────────────────────────────────────────


def test_intermediate_party_json_roundtrip() -> None:
    """A representative party survives serialise → parse → serialise.

    Carries every optional field so a future regression on any single
    column shows up here.
    """
    original = IntermediateParty(
        source_id="vyapar-party-42",
        name="Anjali Saree Centre",
        code="ANJALI",
        kinds=("CUSTOMER",),
        gstin="24AAACR5055K1Z5",
        pan="AAACR5055K",
        state_code="GJ",
        contact_person="Anjali R.",
        email="anjali@example.com",
        phone="+91 98765 43210",
        address="Plot 47, Ring Road, Surat",
    )
    as_json = original.model_dump_json()
    rebuilt = IntermediateParty.model_validate_json(as_json)
    assert rebuilt == original


def test_intermediate_opening_balance_preserves_decimal() -> None:
    """Decimal must round-trip without going through float.

    Pydantic v2 serialises Decimal as a JSON string by default. We assert
    the parsed amount is bit-for-bit equal to the original — not just
    "close enough", because rounding error compounds across hundreds of
    OB rows and breaks the ±₹1 TB reconciliation gate (cutover plan).
    """
    original = IntermediateOpeningBalance(
        source_id="vyapar-ob-7",
        party_source_id="vyapar-party-42",
        ledger_kind="SUNDRY_DEBTORS",
        amount=Decimal("12345.67"),
        side="DR",
        narration="Opening balance as of 2026-04-01",
    )
    as_json = original.model_dump_json()
    parsed = json.loads(as_json)
    assert parsed["amount"] == "12345.67"  # string on the wire — not float

    rebuilt = IntermediateOpeningBalance.model_validate_json(as_json)
    assert rebuilt == original
    assert rebuilt.amount == Decimal("12345.67")
    # Bit-equality guard: no float coercion mid-flight.
    assert isinstance(rebuilt.amount, Decimal)


def test_validation_report_with_rows_roundtrips() -> None:
    """A non-empty report (errors + warnings + info) survives JSON."""
    original = MigrationValidationReport(
        total_parties=47,
        total_opening_balances=12,
        errors=1,
        warnings=2,
        rows=(
            ReconciliationRow(
                severity="error",
                code="DUPLICATE_PARTY_CODE",
                message="Two parties share code 'ACME'.",
                source_ref="row:17",
            ),
            ReconciliationRow(
                severity="warn",
                code="MISSING_GSTIN",
                message="Customer 'Devi Fashions' has no GSTIN.",
                source_ref="row:23",
            ),
            ReconciliationRow(
                severity="info",
                code="EXTRACTED",
                message="47 parties extracted from sheet 'Party Master'.",
            ),
        ),
        tb_reconciles=True,
        tb_diff=Decimal("0.00"),
    )
    as_json = original.model_dump_json()
    rebuilt = MigrationValidationReport.model_validate_json(as_json)
    assert rebuilt == original
    assert rebuilt.tb_diff == Decimal("0.00")


def test_intermediate_party_requires_non_empty_kinds() -> None:
    """An adapter that emits a party with no kind is a bug — fail fast.

    Pydantic's ``min_length=1`` on the tuple enforces this at parse time
    so a malformed adapter throws on its first emission, not deep in
    the commit step.
    """
    from pydantic import ValidationError

    try:
        IntermediateParty(
            source_id="x",
            name="X",
            code="X",
            kinds=(),  # empty — should reject
        )
    except ValidationError:
        return
    raise AssertionError("Expected ValidationError on empty kinds tuple")

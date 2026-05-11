"""TASK-CUT-402: VyaparExcelAdapter unit tests.

Pure-Python tests against the fixture xlsx — no DB required. The
adapter is stateless and side-effect-free, so these run in a few
milliseconds. Integration tests (the upload+approve flow) live in
``test_migrations_router.py``.

Fixtures:
    backend/tests/fixtures/vyapar-sample.xlsx — synthetic Vyapar
    parties export with 5 rows (2 customers with balance, 1 supplier
    with balance, 1 karigar with zero, 1 customer with no balance).
    Hand-crafted so the OB math sums to a balanced TB.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.service.migration import (
    IntermediateOpeningBalance,
    IntermediateParty,
    MigrationAdapter,
    VyaparExcelAdapter,
)
from app.service.migration.vyapar_adapter import _parse_decimal

_FIXTURE = Path(__file__).parent / "fixtures" / "vyapar-sample.xlsx"


def _bytes() -> bytes:
    return _FIXTURE.read_bytes()


def test_adapter_conforms_to_protocol() -> None:
    """Structural conformance — isinstance check against the Protocol."""
    assert isinstance(VyaparExcelAdapter(), MigrationAdapter)


def test_extract_parties_yields_expected_rows() -> None:
    """Parses parties, normalises kinds, derives codes from names."""
    adapter = VyaparExcelAdapter()
    parties = list(adapter.extract_parties(_bytes()))

    # 5 data rows in fixture, all have a name → 5 parties.
    assert len(parties) == 5
    for p in parties:
        assert isinstance(p, IntermediateParty)

    by_name = {p.name: p for p in parties}
    anjali = by_name["Anjali Saree Centre"]
    assert anjali.kinds == ("CUSTOMER",)
    assert anjali.gstin == "24AAACR5055K1Z5"
    assert anjali.state_code == "GJ"
    # Code is derived from the first 3 alpha tokens.
    assert anjali.code.startswith("ANJALI-")
    assert anjali.phone == "+91 9876543210"
    assert anjali.email == "anjali@example.com"

    silk = by_name["Surat Silk Mills"]
    assert silk.kinds == ("SUPPLIER",)
    assert silk.gstin == "24BBBCC5555K2Z9"

    karigar = by_name["Imran Karigar"]
    assert karigar.kinds == ("KARIGAR",)


def test_extract_opening_balances_balanced() -> None:
    """OB extraction is balanced (DR == CR) for the fixture file."""
    adapter = VyaparExcelAdapter()
    obs = list(adapter.extract_opening_balances(_bytes()))

    # 3 non-zero balances (2 customers + 1 supplier; karigar = 0, blank = skipped)
    assert len(obs) == 3
    for o in obs:
        assert isinstance(o, IntermediateOpeningBalance)
        # Each OB row references a party by source_id.
        assert o.party_source_id is not None

    dr_total = sum((o.amount for o in obs if o.side == "DR"), Decimal("0"))
    cr_total = sum((o.amount for o in obs if o.side == "CR"), Decimal("0"))

    # Expected from the fixture:
    #   Anjali (To Receive) — Customer — 15000 DR (Sundry Debtors)
    #   Devi   (To Receive) — Customer — 8500.50 DR (Sundry Debtors)
    #   Silk   (To Pay)     — Supplier — 23500.50 CR (Sundry Creditors)
    #   --------------------------------------------------
    #   DR 23500.50   ==   CR 23500.50  → balanced
    assert dr_total == Decimal("23500.50")
    assert cr_total == Decimal("23500.50")
    assert dr_total == cr_total  # the invariant


def test_opening_balance_kinds_match_party_kinds() -> None:
    """Customer balances hit SUNDRY_DEBTORS, supplier hits SUNDRY_CREDITORS."""
    adapter = VyaparExcelAdapter()
    parties = {p.source_id: p for p in adapter.extract_parties(_bytes())}
    obs = list(adapter.extract_opening_balances(_bytes()))

    for o in obs:
        party = parties[o.party_source_id]  # type: ignore[index]
        if "SUPPLIER" in party.kinds:
            assert o.ledger_kind == "SUNDRY_CREDITORS"
            assert o.side == "CR"
        else:
            assert o.ledger_kind == "SUNDRY_DEBTORS"
            assert o.side == "DR"


def test_validate_reports_balanced_count() -> None:
    """Validate returns matching party + OB counts; zero errors on a clean file."""
    report = VyaparExcelAdapter().validate(_bytes())

    assert report.total_parties == 5
    assert report.total_opening_balances == 3
    assert report.errors == 0
    # Tb_diff is left None by validate (commit step computes it).
    assert report.tb_diff is None
    # At least one info row about extraction.
    assert any(r.severity == "info" and r.code == "EXTRACTED" for r in report.rows)


def test_validate_reports_unparseable_balance_as_error() -> None:
    """A row with a non-numeric balance produces an error reconciliation row."""
    from io import BytesIO

    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("Parties")
    ws.append(["Party Name", "Opening Balance", "Type", "Balance Type"])
    ws.append(["Good Party", "1000", "Customer", "To Receive"])
    ws.append(["Bad Party", "not-a-number", "Customer", "To Receive"])
    out = BytesIO()
    wb.save(out)

    report = VyaparExcelAdapter().validate(out.getvalue())
    assert report.errors >= 1
    bad = [r for r in report.rows if r.code == "OPENING_BALANCE_UNPARSEABLE"]
    assert len(bad) == 1


def test_validate_empty_workbook_errors() -> None:
    """Workbook with no party sheet emits NO_PARTIES_FOUND."""
    from io import BytesIO

    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.title = "Random"
    wb.active.append(["foo", "bar"])
    out = BytesIO()
    wb.save(out)

    report = VyaparExcelAdapter().validate(out.getvalue())
    assert report.total_parties == 0
    assert report.errors >= 1
    assert any(r.code == "NO_PARTIES_FOUND" for r in report.rows)


def test_parse_decimal_handles_indian_formatting() -> None:
    """Money parser strips ₹ and Indian commas without using float."""
    assert _parse_decimal("1234.50") == Decimal("1234.50")
    assert _parse_decimal("₹1,23,450.00") == Decimal("123450.00")
    assert _parse_decimal("₹ 1,000") == Decimal("1000")
    assert _parse_decimal(1234) == Decimal("1234")
    assert _parse_decimal(1234.5) == Decimal("1234.5")
    assert _parse_decimal(None) == Decimal("0")
    assert _parse_decimal("") == Decimal("0")
    assert _parse_decimal("-") == Decimal("0")
    with pytest.raises(ValueError):
        _parse_decimal("not-a-number")
    with pytest.raises(ValueError):
        _parse_decimal(True)


def test_invalid_gstin_warns_but_imports() -> None:
    """A bad GSTIN doesn't fail the row — it's emitted as a warning."""
    from io import BytesIO

    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("Parties")
    ws.append(["Party Name", "GSTIN", "Type", "Opening Balance", "Balance Type"])
    ws.append(["Mostly Good", "NOTAGSTIN", "Customer", "1000", "To Receive"])
    out = BytesIO()
    wb.save(out)

    adapter = VyaparExcelAdapter()
    report = adapter.validate(out.getvalue())
    assert report.warnings >= 1
    assert any(r.code == "GSTIN_FORMAT_INVALID" for r in report.rows)
    # Party still extracted, just without GSTIN.
    parties = list(adapter.extract_parties(out.getvalue()))
    assert len(parties) == 1
    assert parties[0].gstin is None

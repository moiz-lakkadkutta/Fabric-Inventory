"""System catalog seed — UOMs, HSN, COA structure (TASK-015).

Every new org gets these rows seeded at signup time so its catalogue is
ready for Item / Ledger / Voucher work without manual setup. Idempotent —
re-running is a no-op success (mirrors the `rbac_service.seed_*`
contract).

What's seeded:
- 10 UOM rows covering the textile-trade common cases (METER, PIECE, KG,
  LITER, SET, GROSS, DOZEN, ROLL, BUNDLE, OTHER) — the full enum domain.
- 10 HSN rows: textile-trade common HSN codes with their GST rates.
- COA: 5 top-level groups (Asset / Liability / Equity / Revenue / Expense)
  + a starter set of system ledgers under each (Cash, Bank, AR, AP,
  Inventory, Sales, Purchases, Capital, Tax Payable, Salaries).
  Trial-balance balanced (all opening balances = 0).

Demo data (a fully-populated dev org with parties + items) is intentionally
out-of-scope here — that's a separate `make seed-demo` workflow when one
is needed; until then, every test or dev session signs up its own org via
`/auth/signup` which fires this catalogue seed.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CoaGroup, Hsn, Ledger, Uom
from app.models.masters import UomType

# ──────────────────────────────────────────────────────────────────────
# UOM catalog
# ──────────────────────────────────────────────────────────────────────

# (code, display name, uom_type)
_SYSTEM_UOMS: list[tuple[str, str, UomType]] = [
    ("MTR", "Meter", UomType.METER),
    ("PCS", "Piece", UomType.PIECE),
    ("KG", "Kilogram", UomType.KG),
    ("LTR", "Liter", UomType.LITER),
    ("SET", "Set", UomType.SET),
    ("GRS", "Gross", UomType.GROSS),
    ("DOZ", "Dozen", UomType.DOZEN),
    ("ROL", "Roll", UomType.ROLL),
    ("BDL", "Bundle", UomType.BUNDLE),
    ("OTH", "Other", UomType.OTHER),
]


def seed_uoms(session: Session, *, org_id: uuid.UUID) -> dict[str, Uom]:
    """Seed the UOM catalog for `org_id`. Idempotent."""
    existing = {
        row.code: row for row in session.execute(select(Uom).where(Uom.org_id == org_id)).scalars()
    }
    created: dict[str, Uom] = dict(existing)
    for code, name, uom_type in _SYSTEM_UOMS:
        if code in existing:
            continue
        row = Uom(org_id=org_id, code=code, name=name, uom_type=uom_type)
        session.add(row)
        created[code] = row
    session.flush()
    return created


# ──────────────────────────────────────────────────────────────────────
# HSN catalog
# ──────────────────────────────────────────────────────────────────────

# (hsn_code, description, gst_rate_percent). Picked for textile trade —
# Moiz's domain. Real catalog has thousands of codes; these 10 cover the
# vast majority of ladies-suit / fabric SKUs at MVP scale.
_SYSTEM_HSN: list[tuple[str, str, Decimal]] = [
    ("5208", "Cotton woven fabric (≤ 200 g/m²)", Decimal("5.00")),
    ("5210", "Cotton woven fabric, mixed (≤ 200 g/m²)", Decimal("5.00")),
    ("5407", "Synthetic filament woven fabric", Decimal("5.00")),
    ("5408", "Artificial filament woven fabric", Decimal("5.00")),
    ("5512", "Synthetic staple fibre woven fabric", Decimal("5.00")),
    ("5515", "Mixed-fibre woven fabric", Decimal("5.00")),
    ("5810", "Embroidery in the piece, in strips, etc.", Decimal("12.00")),
    ("6204", "Women's suits / ensembles / dresses", Decimal("12.00")),
    ("6217", "Made-up clothing accessories (scarves, belts)", Decimal("12.00")),
    ("9988", "Job work — textile services", Decimal("5.00")),
]


def seed_hsn(session: Session, *, org_id: uuid.UUID) -> dict[str, Hsn]:
    """Seed the HSN catalog for `org_id`. Idempotent."""
    existing = {
        row.hsn_code: row
        for row in session.execute(select(Hsn).where(Hsn.org_id == org_id)).scalars()
    }
    created: dict[str, Hsn] = dict(existing)
    for code, description, rate in _SYSTEM_HSN:
        if code in existing:
            continue
        row = Hsn(
            org_id=org_id,
            hsn_code=code,
            description=description,
            gst_rate=rate,
            is_rcm_applicable=False,
        )
        session.add(row)
        created[code] = row
    session.flush()
    return created


# ──────────────────────────────────────────────────────────────────────
# Chart of accounts
# ──────────────────────────────────────────────────────────────────────

# Top-level groups. (code, name, group_type)
_SYSTEM_COA_GROUPS: list[tuple[str, str, str]] = [
    ("ASSET", "Assets", "ASSET"),
    ("LIABILITY", "Liabilities", "LIABILITY"),
    ("EQUITY", "Equity", "EQUITY"),
    ("REVENUE", "Revenue", "REVENUE"),
    ("EXPENSE", "Expenses", "EXPENSE"),
]

# Starter ledgers. (code, name, ledger_type, parent_group_code, is_control_account)
# `is_control_account=True` means transactions hit a sub-ledger (party, bank)
# rather than this row directly — used for AR/AP and bank ledgers.
_SYSTEM_LEDGERS: list[tuple[str, str, str, str, bool]] = [
    ("1000", "Cash on Hand", "CASH", "ASSET", False),
    ("1100", "Bank Accounts", "BANK", "ASSET", True),
    ("1200", "Sundry Debtors (AR)", "RECEIVABLE", "ASSET", True),
    ("1300", "Inventory", "INVENTORY", "ASSET", False),
    ("2000", "Sundry Creditors (AP)", "PAYABLE", "LIABILITY", True),
    ("2100", "GST Payable", "TAX", "LIABILITY", False),
    ("2200", "TDS Payable", "TAX", "LIABILITY", False),
    ("3000", "Capital Account", "CAPITAL", "EQUITY", False),
    ("3100", "Retained Earnings", "EQUITY", "EQUITY", False),
    ("4000", "Sales Revenue", "REVENUE", "REVENUE", False),
    ("4100", "Other Income", "REVENUE", "REVENUE", False),
    ("5000", "Cost of Goods Sold", "COGS", "EXPENSE", False),
    ("5100", "Salaries & Wages", "EXPENSE", "EXPENSE", False),
    ("5200", "Rent", "EXPENSE", "EXPENSE", False),
    ("5300", "Utilities", "EXPENSE", "EXPENSE", False),
    ("5400", "Bank Charges", "EXPENSE", "EXPENSE", False),
    ("5500", "Office Expenses", "EXPENSE", "EXPENSE", False),
]


def seed_coa(session: Session, *, org_id: uuid.UUID) -> dict[str, Ledger]:
    """Seed the COA groups + starter ledgers for `org_id`. Idempotent.

    Returns a dict keyed by ledger `code`. Group rows are created but not
    returned — callers reach groups via `ledger.coa_group`.
    """
    existing_groups = {
        row.code: row
        for row in session.execute(select(CoaGroup).where(CoaGroup.org_id == org_id)).scalars()
    }
    groups: dict[str, CoaGroup] = dict(existing_groups)
    for code, name, group_type in _SYSTEM_COA_GROUPS:
        if code in groups:
            continue
        row = CoaGroup(
            org_id=org_id,
            code=code,
            name=name,
            group_type=group_type,
            is_system_group=True,
        )
        session.add(row)
        groups[code] = row
    session.flush()

    existing_ledgers = {
        row.code: row
        for row in session.execute(
            select(Ledger).where(Ledger.org_id == org_id, Ledger.firm_id.is_(None))
        ).scalars()
    }
    ledgers: dict[str, Ledger] = dict(existing_ledgers)
    for code, name, ledger_type, parent_code, is_control in _SYSTEM_LEDGERS:
        if code in existing_ledgers:
            continue
        # Catch typos in `_SYSTEM_LEDGERS` early — without this guard a
        # bad parent_code would surface as a confusing KeyError mid-seed.
        if parent_code not in groups:
            raise RuntimeError(
                f"Ledger {code!r} references unknown COA group {parent_code!r}"
            )
        ledger = Ledger(
            org_id=org_id,
            firm_id=None,
            code=code,
            name=name,
            ledger_type=ledger_type,
            coa_group_id=groups[parent_code].coa_group_id,
            is_control_account=is_control,
            opening_balance=Decimal("0.00"),
            is_active=True,
        )
        session.add(ledger)
        ledgers[code] = ledger
    session.flush()
    return ledgers


# ──────────────────────────────────────────────────────────────────────
# Top-level: seed everything for an org
# ──────────────────────────────────────────────────────────────────────


def seed_system_catalog(session: Session, *, org_id: uuid.UUID) -> None:
    """Seed UOMs + HSN + COA for an org. Idempotent. Called automatically
    from `/auth/signup` so every new tenant has a usable catalog from
    minute one.
    """
    seed_uoms(session, org_id=org_id)
    seed_hsn(session, org_id=org_id)
    seed_coa(session, org_id=org_id)


__all__ = [
    "seed_coa",
    "seed_hsn",
    "seed_system_catalog",
    "seed_uoms",
]

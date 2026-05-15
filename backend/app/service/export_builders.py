"""Per-domain export builders — TASK-CUT-403.

Maps list-router result objects into the row + column shape that
``export_service.to_csv`` / ``to_xlsx`` expect. Keeping the column
schemas here (one constant per domain) means routers stay thin and
the same headers ship in CSV and XLSX without drift.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.service.export_service import Column, Sheet

# ──────────────────────────────────────────────────────────────────────
# Filename helpers
# ──────────────────────────────────────────────────────────────────────


def filename_for(stem: str, fmt: str, *, period: str | None = None) -> str:
    """Build a download filename like ``invoices-2026-05-11.csv``.

    Includes today's UTC date so a user who exports twice doesn't collide
    in their Downloads folder. ``period`` overrides the date for reports
    scoped to a custom month (GSTR-1) or range.
    """
    suffix = "csv" if fmt == "csv" else "xlsx"
    stamp = period or dt.date.today().isoformat()
    return f"{stem}-{stamp}.{suffix}"


# ──────────────────────────────────────────────────────────────────────
# Helpers — Decimal coercion (the DB returns Numeric → Python Decimal,
# but JSON-deserialised values in tests can be strings).
# ──────────────────────────────────────────────────────────────────────


def _as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int,)):
        return Decimal(value)
    if isinstance(value, str):
        return Decimal(value)
    return None  # Unknown type — emit blank rather than corrupt.


# ──────────────────────────────────────────────────────────────────────
# Sales invoices
# ──────────────────────────────────────────────────────────────────────


INVOICE_COLUMNS: Sequence[Column] = (
    Column("number", "Invoice #"),
    Column("series", "Series"),
    Column("invoice_date", "Date", "date"),
    Column("party_name", "Party"),
    Column("place_of_supply_state", "POS"),
    Column("status", "Status"),
    Column("invoice_amount", "Amount", "money"),
    Column("gst_amount", "GST", "money"),
    Column("paid_amount", "Paid", "money"),
    Column("due_date", "Due date", "date"),
)


def invoice_export_rows(
    items: Sequence[Any], party_names: dict[uuid.UUID, str]
) -> list[dict[str, Any]]:
    """Map SalesInvoice ORM rows → dict rows for the exporter."""
    out: list[dict[str, Any]] = []
    for inv in items:
        out.append(
            {
                "number": inv.number,
                "series": inv.series,
                "invoice_date": inv.invoice_date,
                "party_name": party_names.get(inv.party_id, ""),
                "place_of_supply_state": inv.place_of_supply_state or "",
                "status": (
                    inv.lifecycle_status.value
                    if hasattr(inv.lifecycle_status, "value")
                    else inv.lifecycle_status
                ),
                "invoice_amount": _as_decimal(inv.invoice_amount),
                "gst_amount": _as_decimal(inv.gst_amount),
                "paid_amount": _as_decimal(inv.paid_amount),
                "due_date": inv.due_date,
            }
        )
    return out


# ──────────────────────────────────────────────────────────────────────
# Parties
# ──────────────────────────────────────────────────────────────────────


PARTY_COLUMNS: Sequence[Column] = (
    Column("code", "Code"),
    Column("name", "Name"),
    Column("legal_name", "Legal name"),
    Column("kind", "Kind"),
    Column("gstin", "GSTIN"),
    Column("pan", "PAN"),
    Column("state_code", "State"),
    Column("email", "Email"),
    Column("phone", "Phone"),
    Column("is_active", "Active"),
)


def _party_kind(party: Any) -> str:
    """First-match kind label so the CSV/XLSX is single-valued per row.

    The Party model carries four orthogonal booleans (is_customer /
    is_supplier / is_karigar / is_transporter). For the export we pick
    the first match in priority order — same order the FE pill
    renders — so the column is sortable in Excel.
    """
    if party.is_customer:
        return "Customer"
    if party.is_supplier:
        return "Supplier"
    if party.is_karigar:
        return "Karigar"
    if party.is_transporter:
        return "Transporter"
    return ""


def party_export_rows(parties: Sequence[Any]) -> list[dict[str, Any]]:
    """Decrypt PII columns + flatten for export.

    GSTIN, PAN, phone are PII columns encrypted at rest; the router
    receives the decrypted PartyResponse, so by the time we hit this
    function the strings are plaintext. Caller passes the *response*
    objects, not the raw Party ORM rows.
    """
    out: list[dict[str, Any]] = []
    for p in parties:
        out.append(
            {
                "code": p.code,
                "name": p.name,
                "legal_name": p.legal_name or "",
                "kind": _party_kind(p),
                "gstin": p.gstin or "",
                "pan": p.pan or "",
                "state_code": p.state_code or "",
                "email": p.email or "",
                "phone": p.phone or "",
                "is_active": "Y" if p.is_active else "N",
            }
        )
    return out


# ──────────────────────────────────────────────────────────────────────
# Items
# ──────────────────────────────────────────────────────────────────────


ITEM_COLUMNS: Sequence[Column] = (
    Column("code", "Code"),
    Column("name", "Name"),
    Column("item_type", "Type"),
    Column("primary_uom", "UOM"),
    Column("hsn_code", "HSN"),
    Column("gst_rate", "GST %", "number"),
    Column("category", "Category"),
    Column("is_active", "Active"),
)


def item_export_rows(items: Sequence[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for it in items:
        item_type = it.item_type.value if hasattr(it.item_type, "value") else it.item_type
        uom = it.primary_uom.value if hasattr(it.primary_uom, "value") else it.primary_uom
        out.append(
            {
                "code": it.code,
                "name": it.name,
                "item_type": item_type or "",
                "primary_uom": uom or "",
                "hsn_code": it.hsn_code or "",
                "gst_rate": _as_decimal(it.gst_rate),
                "category": it.category or "",
                "is_active": "Y" if it.is_active else "N",
            }
        )
    return out


# ──────────────────────────────────────────────────────────────────────
# Receipts — list rows
# ──────────────────────────────────────────────────────────────────────


RECEIPT_COLUMNS: Sequence[Column] = (
    Column("voucher_no", "Receipt #"),
    Column("voucher_date", "Date", "date"),
    Column("party_name", "Party"),
    Column("mode", "Mode"),
    Column("amount", "Amount", "money"),
    Column("allocations", "Allocations"),
    Column("narration", "Narration"),
)


def receipt_export_rows(entries: Sequence[Any]) -> list[dict[str, Any]]:
    """Map ``ReceiptListEntry`` records into export rows.

    Allocations is a flat "INV-1/RT (₹500); INV-2/RT (₹500)" string so
    the user can audit FIFO matching without opening each receipt.
    """
    out: list[dict[str, Any]] = []
    for e in entries:
        allocations = "; ".join(
            f"{series}/{number} (₹{amount})" for (number, series, amount) in e.allocations
        )
        out.append(
            {
                "voucher_no": f"{e.voucher.series}/{e.voucher.number}",
                "voucher_date": e.voucher.voucher_date,
                "party_name": e.party_name or "",
                "mode": e.mode or "",
                "amount": _as_decimal(e.voucher.total_debit),
                "allocations": allocations,
                "narration": e.voucher.narration or "",
            }
        )
    return out


# ──────────────────────────────────────────────────────────────────────
# Vouchers
# ──────────────────────────────────────────────────────────────────────


VOUCHER_COLUMNS: Sequence[Column] = (
    Column("voucher_no", "Voucher #"),
    Column("voucher_type", "Type"),
    Column("voucher_date", "Date", "date"),
    Column("narration", "Narration"),
    Column("total_debit", "Debit", "money"),
    Column("total_credit", "Credit", "money"),
    Column("status", "Status"),
)


def voucher_export_rows(vouchers: Sequence[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for v in vouchers:
        vtype = v.voucher_type.value if hasattr(v.voucher_type, "value") else v.voucher_type
        status_val = v.status.value if hasattr(v.status, "value") else v.status
        out.append(
            {
                "voucher_no": f"{v.series}/{v.number}",
                "voucher_type": vtype or "",
                "voucher_date": v.voucher_date,
                "narration": v.narration or "",
                "total_debit": _as_decimal(v.total_debit),
                "total_credit": _as_decimal(v.total_credit),
                "status": status_val or "",
            }
        )
    return out


# ──────────────────────────────────────────────────────────────────────
# Bank accounts (TASK-CUT-501b)
# ──────────────────────────────────────────────────────────────────────


BANK_ACCOUNT_COLUMNS: Sequence[Column] = (
    Column("bank_name", "Bank"),
    Column("account_number", "Account #"),
    Column("ifsc_code", "IFSC"),
    Column("account_type", "Type"),
    Column("balance", "Balance", "money"),
    Column("last_reconciled_date", "Last reconciled", "date"),
)


def bank_account_export_rows(accounts: Sequence[Any]) -> list[dict[str, Any]]:
    """Decrypt PII + flatten for export.

    Caller passes `BankAccountResponse` schema objects (where
    `account_number` is already plaintext via the router's
    `_to_bank_response` decrypt helper), not the raw BankAccount ORM
    rows whose `account_number` is cipher bytes.
    """
    out: list[dict[str, Any]] = []
    for a in accounts:
        out.append(
            {
                "bank_name": a.bank_name or "",
                "account_number": a.account_number or "",
                "ifsc_code": a.ifsc_code or "",
                "account_type": a.account_type or "",
                "balance": _as_decimal(a.balance),
                "last_reconciled_date": a.last_reconciled_date,
            }
        )
    return out


# ──────────────────────────────────────────────────────────────────────
# Cheques (TASK-CUT-501b)
# ──────────────────────────────────────────────────────────────────────


CHEQUE_COLUMNS: Sequence[Column] = (
    Column("cheque_number", "Cheque #"),
    Column("cheque_date", "Date", "date"),
    Column("payee_name", "Payee"),
    Column("amount", "Amount", "money"),
    Column("status", "Status"),
    Column("clearing_date", "Cleared", "date"),
    Column("bounce_reason", "Bounce reason"),
)


def cheque_export_rows(cheques: Sequence[Any]) -> list[dict[str, Any]]:
    """Map ``ChequeResponse``/Cheque ORM rows → export dicts.

    Status is an enum on the wire — coerce to its string value so the
    cell renders as plain text, not the Python enum repr.
    """
    out: list[dict[str, Any]] = []
    for c in cheques:
        status_val = c.status.value if hasattr(c.status, "value") else c.status
        out.append(
            {
                "cheque_number": c.cheque_number,
                "cheque_date": c.cheque_date,
                "payee_name": c.payee_name or "",
                "amount": _as_decimal(c.amount),
                "status": status_val or "",
                "clearing_date": c.clearing_date,
                "bounce_reason": c.bounce_reason or "",
            }
        )
    return out


# ──────────────────────────────────────────────────────────────────────
# Reports
# ──────────────────────────────────────────────────────────────────────


PNL_COLUMNS: Sequence[Column] = (
    Column("group_code", "Group"),
    Column("group_name", "Name"),
    Column("group_type", "Type"),
    Column("current_period_amount", "Current period", "money"),
    Column("prior_period_amount", "Prior period", "money"),
)


def pnl_export_rows(buckets: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        {
            "group_code": b.code,
            "group_name": b.name,
            "group_type": (b.group_type.value if hasattr(b.group_type, "value") else b.group_type),
            "current_period_amount": _as_decimal(b.current_amount),
            "prior_period_amount": _as_decimal(b.prior_amount),
        }
        for b in buckets
    ]


TB_COLUMNS: Sequence[Column] = (
    Column("ledger_code", "Code"),
    Column("ledger_name", "Ledger"),
    Column("group_code", "Group"),
    Column("debit", "Debit", "money"),
    Column("credit", "Credit", "money"),
)


def tb_export_rows(rows: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        {
            "ledger_code": r.ledger_code,
            "ledger_name": r.ledger_name,
            "group_code": r.group_code,
            "debit": _as_decimal(r.debit),
            "credit": _as_decimal(r.credit),
        }
        for r in rows
    ]


DAYBOOK_COLUMNS: Sequence[Column] = (
    Column("voucher_no", "Voucher #"),
    Column("voucher_type", "Type"),
    Column("narration", "Narration"),
    Column("party_name", "Party"),
    Column("total_debit", "Debit", "money"),
    Column("total_credit", "Credit", "money"),
)


def daybook_export_rows(vouchers: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        {
            "voucher_no": f"{v.series}/{v.number}",
            "voucher_type": (
                v.voucher_type.value if hasattr(v.voucher_type, "value") else v.voucher_type
            ),
            "narration": v.narration or "",
            "party_name": v.party_name or "",
            "total_debit": _as_decimal(v.total_debit),
            "total_credit": _as_decimal(v.total_credit),
        }
        for v in vouchers
    ]


STOCK_COLUMNS: Sequence[Column] = (
    Column("item_code", "Item code"),
    Column("item_name", "Item name"),
    Column("sku_code", "SKU"),
    Column("uom", "UOM"),
    Column("on_hand_qty", "On hand", "number"),
    Column("avg_cost", "Avg cost", "money"),
    Column("valuation", "Valuation", "money"),
)


def stock_export_rows(rows: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        {
            "item_code": r.item_code,
            "item_name": r.item_name,
            "sku_code": r.sku_code or "",
            "uom": r.uom or "",
            "on_hand_qty": _as_decimal(r.on_hand_qty),
            "avg_cost": _as_decimal(r.avg_cost),
            "valuation": _as_decimal(r.valuation),
        }
        for r in rows
    ]


# ──────────────────────────────────────────────────────────────────────
# GSTR-1 — five-bucket multi-sheet workbook
# ──────────────────────────────────────────────────────────────────────


# NOTE: column ``key`` must match the field name on the row dataclass
# (`_Gstr1InvoiceRow` / `_Gstr1B2csRow` / `_Gstr1HsnRow` in
# reports_service, mirrored by the Pydantic models in schemas.reports).
# ``_as_dict`` below does `getattr(row, c.key, None)`, so any drift
# silently renders empty cells in the CSV / XLSX. The headers ("GSTIN",
# "Invoice #", "Qty", "CGST", "SGST", "IGST") stay human-friendly —
# only the lookup ``key`` is constrained.
GSTR1_INVOICE_COLUMNS: Sequence[Column] = (
    Column("number", "Invoice #"),
    Column("invoice_date", "Date", "date"),
    Column("party_name", "Party"),
    Column("gstin", "GSTIN"),
    Column("place_of_supply_state", "POS"),
    Column("invoice_value", "Total", "money"),
    Column("taxable_value", "Taxable", "money"),
    Column("igst", "IGST", "money"),
    Column("cgst", "CGST", "money"),
    Column("sgst", "SGST", "money"),
    Column("gst_rate", "GST rate %", "number"),
)


GSTR1_B2CS_COLUMNS: Sequence[Column] = (
    Column("place_of_supply_state", "POS"),
    Column("gst_rate", "GST rate %", "number"),
    Column("taxable_value", "Taxable", "money"),
    Column("igst", "IGST", "money"),
    Column("cgst", "CGST", "money"),
    Column("sgst", "SGST", "money"),
)


GSTR1_HSN_COLUMNS: Sequence[Column] = (
    Column("hsn_code", "HSN"),
    Column("description", "Description"),
    Column("uom", "UOM"),
    Column("total_qty", "Qty", "number"),
    Column("total_value", "Total", "money"),
    Column("taxable_value", "Taxable", "money"),
    Column("igst", "IGST", "money"),
    Column("cgst", "CGST", "money"),
    Column("sgst", "SGST", "money"),
)


@dataclass(frozen=True, slots=True)
class _Gstr1Row:
    """Adapter so the export can read both attribute- and key-style
    GSTR-1 rows. compute_gstr1 emits frozen dataclasses; we don't want
    the export builder to import their concrete types."""

    data: dict[str, Any]

    def __getattr__(self, name: str) -> Any:
        return self.data.get(name)


def _as_dict(row: Any, keys: Sequence[Column]) -> dict[str, Any]:
    return {c.key: getattr(row, c.key, None) for c in keys}


def gstr1_sheets(result: Any) -> list[Sheet]:
    """Build the 5-sheet workbook spec from compute_gstr1's result.

    Order matches the FE tab + government schedule order: B2B, B2CL,
    B2CS, Export, HSN.
    """
    return [
        Sheet(
            name="B2B",
            columns=GSTR1_INVOICE_COLUMNS,
            rows=[_as_dict(inv, GSTR1_INVOICE_COLUMNS) for inv in result.b2b],
        ),
        Sheet(
            name="B2CL",
            columns=GSTR1_INVOICE_COLUMNS,
            rows=[_as_dict(inv, GSTR1_INVOICE_COLUMNS) for inv in result.b2cl],
        ),
        Sheet(
            name="B2CS",
            columns=GSTR1_B2CS_COLUMNS,
            rows=[_as_dict(row, GSTR1_B2CS_COLUMNS) for row in result.b2cs],
        ),
        Sheet(
            name="Export",
            columns=GSTR1_INVOICE_COLUMNS,
            rows=[_as_dict(inv, GSTR1_INVOICE_COLUMNS) for inv in result.export],
        ),
        Sheet(
            name="HSN",
            columns=GSTR1_HSN_COLUMNS,
            rows=[_as_dict(row, GSTR1_HSN_COLUMNS) for row in result.hsn],
        ),
    ]

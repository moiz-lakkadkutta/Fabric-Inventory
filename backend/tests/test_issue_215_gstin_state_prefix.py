"""#215 — a GSTIN whose first two digits are not a GST state/UT code.

Before: party validation only checked ``^\\d{2}`` for the state prefix, so a
party with GSTIN ``99…`` / ``00…`` and no recorded state_code was accepted;
``create_draft_invoice`` then derived no buyer state from the GSTIN, the PoS
engine saw no destination and returned NIL_NOT_A_SUPPLY — a registered B2B
sale silently invoiced with ₹0 GST.

After (both halves):
  1. Party GSTIN validation (create + update-when-changed + Vyapar import)
     requires the prefix to be a valid GST state/UT code (01-38, 97).
     Legacy parties already holding a bad GSTIN are NOT touched: editing an
     unrelated field (or re-sending the unchanged GSTIN, as the edit form
     does) still works.
  2. ``create_draft_invoice`` / ``finalize_invoice`` refuse (422) a
     GSTIN-bearing buyer that resolves to NIL_NOT_A_SUPPLY outside a
     same-GSTIN branch transfer.

PENDING MOIZ+CA SIGN-OFF (GST treatment).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError
from app.models import Firm, Item, Party, SalesInvoice
from app.models.masters import ItemType, TrackingType, UomType
from app.service import masters_service, sales_service
from app.service.gst_service import DocumentType, TaxType
from app.service.migration import VyaparExcelAdapter
from app.utils.crypto import decrypt_pii, encrypt_pii, get_org_dek
from app.utils.gst_states import gstin_validation_error

BAD_99 = "99AABCX1234C1Z5"
BAD_00 = "00AABCX1234C1Z5"
GOOD_MH = "27AABCM1234C1Z9"


# ──────────────────────────────────────────────────────────────────────
# Pure validator
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("prefix", ["00", "39", "40", "96", "98", "99"])
def test_validator_rejects_non_state_prefixes(prefix: str) -> None:
    err = gstin_validation_error(f"{prefix}AABCX1234C1Z5")
    assert err is not None
    assert f"state code '{prefix}'" in err
    assert "not a valid Indian state/UT code" in err


@pytest.mark.parametrize("prefix", ["01", "07", "24", "27", "36", "37", "38", "97"])
def test_validator_accepts_state_prefixes(prefix: str) -> None:
    assert gstin_validation_error(f"{prefix}AABCX1234C1Z5") is None


def test_validator_still_rejects_bad_format() -> None:
    err = gstin_validation_error("bogus")
    assert err is not None and "format" in err.lower()


# ──────────────────────────────────────────────────────────────────────
# Party create / update
# ──────────────────────────────────────────────────────────────────────


def _create(db_session: OrmSession, org_id: uuid.UUID, **kw: object) -> Party:
    return masters_service.create_party(
        db_session,
        org_id=org_id,
        firm_id=None,
        code=f"P{uuid.uuid4().hex[:6].upper()}",
        name="Prefix Test",
        is_customer=True,
        **kw,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("gstin", [BAD_99, BAD_00])
def test_create_party_rejects_non_state_gstin_prefix(
    db_session: OrmSession, fresh_org_id: uuid.UUID, gstin: str
) -> None:
    with pytest.raises(AppValidationError, match=r"GSTIN state code '(99|00)'"):
        _create(db_session, fresh_org_id, gstin=gstin)


@pytest.mark.parametrize("gstin", ["38AABCL1234C1Z5", "97AABCO1234C1Z5", GOOD_MH])
def test_create_party_accepts_ladakh_other_territory_and_states(
    db_session: OrmSession, fresh_org_id: uuid.UUID, gstin: str
) -> None:
    party = _create(db_session, fresh_org_id, gstin=gstin)
    dek = get_org_dek(db_session, org_id=fresh_org_id)
    assert decrypt_pii(party.gstin, dek=dek, org_id=fresh_org_id) == gstin


def test_update_party_rejects_new_non_state_gstin_prefix(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    party = _create(db_session, fresh_org_id, gstin=GOOD_MH)
    with pytest.raises(AppValidationError, match="GSTIN state code '99'"):
        masters_service.update_party(
            db_session, org_id=fresh_org_id, party_id=party.party_id, gstin=BAD_99
        )


def _legacy_bad_party(db_session: OrmSession, org_id: uuid.UUID, **kw: object) -> Party:
    """A party written before #215 (bypasses the validator, as legacy rows did)."""
    dek = get_org_dek(db_session, org_id=org_id)
    party = Party(
        org_id=org_id,
        code=f"L{uuid.uuid4().hex[:6].upper()}",
        name="Legacy Bad GSTIN",
        is_customer=True,
        gstin=encrypt_pii(BAD_99, dek=dek, org_id=org_id),
        **kw,
    )
    db_session.add(party)
    db_session.flush()
    return party


def test_legacy_bad_gstin_party_unrelated_edit_still_works(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    party = _legacy_bad_party(db_session, fresh_org_id)
    updated = masters_service.update_party(
        db_session, org_id=fresh_org_id, party_id=party.party_id, name="Renamed", notes="x"
    )
    assert updated.name == "Renamed"


def test_legacy_bad_gstin_party_resending_unchanged_gstin_still_works(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """The party edit form re-sends the GSTIN on every save; an unchanged
    legacy value must not block an unrelated edit (e.g. adding state_code)."""
    party = _legacy_bad_party(db_session, fresh_org_id)
    updated = masters_service.update_party(
        db_session,
        org_id=fresh_org_id,
        party_id=party.party_id,
        gstin=BAD_99,
        state_code="MH",
    )
    assert updated.state_code == "MH"
    dek = get_org_dek(db_session, org_id=fresh_org_id)
    assert decrypt_pii(updated.gstin, dek=dek, org_id=fresh_org_id) == BAD_99


def test_legacy_bad_gstin_party_can_be_corrected(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    party = _legacy_bad_party(db_session, fresh_org_id)
    updated = masters_service.update_party(
        db_session, org_id=fresh_org_id, party_id=party.party_id, gstin=GOOD_MH
    )
    dek = get_org_dek(db_session, org_id=fresh_org_id)
    assert decrypt_pii(updated.gstin, dek=dek, org_id=fresh_org_id) == GOOD_MH
    with pytest.raises(AppValidationError, match="GSTIN state code '00'"):
        masters_service.update_party(
            db_session, org_id=fresh_org_id, party_id=party.party_id, gstin=BAD_00
        )


# ──────────────────────────────────────────────────────────────────────
# Vyapar import
# ──────────────────────────────────────────────────────────────────────


def _vyapar_xlsx(gstin: str) -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("Parties")
    ws.append(["Party Name", "GSTIN", "Type", "Opening Balance", "Balance Type"])
    ws.append(["Bad Prefix Traders", gstin, "Customer", "1000", "To Receive"])
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def test_vyapar_import_drops_non_state_gstin_with_warning() -> None:
    """Same rule as the party API: a 99-prefix GSTIN is dropped (party still
    imports, unregistered) with a reconciliation warning — never passed to
    create_party, which would abort the whole migration."""
    src = _vyapar_xlsx(BAD_99)
    adapter = VyaparExcelAdapter()
    report = adapter.validate(src)
    msgs = [r.message for r in report.rows if r.code == "GSTIN_FORMAT_INVALID"]
    assert msgs and "state code '99'" in msgs[0]
    parties = list(adapter.extract_parties(src))
    assert len(parties) == 1
    assert parties[0].gstin is None


def test_vyapar_import_keeps_valid_gstin() -> None:
    parties = list(VyaparExcelAdapter().extract_parties(_vyapar_xlsx(GOOD_MH)))
    assert parties[0].gstin == GOOD_MH


# ──────────────────────────────────────────────────────────────────────
# Invoice guard (service)
# ──────────────────────────────────────────────────────────────────────


def _seed(db_session: OrmSession, org_id: uuid.UUID) -> tuple[Firm, Item]:
    from app.service.seed_service import seed_coa

    seed_coa(db_session, org_id=org_id)
    firm = Firm(
        org_id=org_id,
        code=f"F{uuid.uuid4().hex[:6]}",
        name="Seller",
        has_gst=True,
        state_code="MH",
    )
    db_session.add(firm)
    item = Item(
        org_id=org_id,
        code=f"I{uuid.uuid4().hex[:6]}",
        name="Georgette",
        item_type=ItemType.FINISHED,
        tracking=TrackingType.NONE,
        primary_uom=UomType.METER,
    )
    db_session.add(item)
    db_session.flush()
    return firm, item


def _draft(
    db_session: OrmSession,
    org_id: uuid.UUID,
    firm: Firm,
    item: Item,
    party: Party,
    **kw: object,
) -> SalesInvoice:
    return sales_service.create_draft_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        invoice_date=datetime.date(2026, 9, 2),
        lines=[
            {
                "item_id": item.item_id,
                "qty": Decimal("10"),
                "price": Decimal("50"),
                "gst_rate": Decimal("5"),
                "sequence": 1,
            }
        ],
        **kw,  # type: ignore[arg-type]
    )


def test_draft_invoice_for_bad_prefix_gstin_buyer_without_state_is_422(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Repro of #215: before the fix this produced NIL_NOT_A_SUPPLY / ₹0 GST."""
    firm, item = _seed(db_session, fresh_org_id)
    party = _legacy_bad_party(db_session, fresh_org_id)
    with pytest.raises(AppValidationError) as exc:
        _draft(db_session, fresh_org_id, firm, item, party)
    msg = str(exc.value)
    assert "place of supply" in msg.lower()
    assert "Legacy Bad GSTIN" in msg
    assert "state" in msg.lower()
    # Nothing persisted.
    count = db_session.execute(
        select(SalesInvoice).where(SalesInvoice.org_id == fresh_org_id)
    ).all()
    assert count == []


def test_draft_invoice_bad_prefix_buyer_with_recorded_state_is_taxed(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """The actionable fix the 422 suggests (record the state) works."""
    firm, item = _seed(db_session, fresh_org_id)
    party = _legacy_bad_party(db_session, fresh_org_id, state_code="GJ")
    inv = _draft(db_session, fresh_org_id, firm, item, party)
    assert inv.tax_type == TaxType.IGST.value
    assert inv.gst_amount == Decimal("25.00")


def test_draft_invoice_bad_prefix_buyer_with_ship_to_state_is_taxed(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    firm, item = _seed(db_session, fresh_org_id)
    party = _legacy_bad_party(db_session, fresh_org_id)
    inv = _draft(db_session, fresh_org_id, firm, item, party, ship_to_state="MH")
    assert inv.tax_type == TaxType.CGST_SGST.value
    assert inv.gst_amount == Decimal("25.00")


def test_branch_transfer_still_allowed(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    """Same-GSTIN branch transfer is the one legitimate NIL_NOT_A_SUPPLY for a
    GSTIN-bearing buyer — the guard must not block it."""
    firm, item = _seed(db_session, fresh_org_id)
    dek = get_org_dek(db_session, org_id=fresh_org_id)
    firm.gstin = encrypt_pii(GOOD_MH, dek=dek, org_id=fresh_org_id)
    branch = Party(
        org_id=fresh_org_id,
        code=f"B{uuid.uuid4().hex[:6]}",
        name="Other Branch",
        is_customer=True,
        gstin=encrypt_pii(GOOD_MH, dek=dek, org_id=fresh_org_id),
    )
    db_session.add(branch)
    db_session.flush()
    inv = _draft(db_session, fresh_org_id, firm, item, branch)
    assert inv.tax_type == TaxType.NIL_NOT_A_SUPPLY.value
    assert inv.invoice_type == DocumentType.DELIVERY_CHALLAN.value


def test_finalize_refuses_pre_fix_nil_draft_for_gstin_buyer(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """A draft created before the fix (stored NIL_NOT_A_SUPPLY, TAX_INVOICE,
    GSTIN buyer) must not be finalized into a ₹0-GST tax invoice."""
    firm, item = _seed(db_session, fresh_org_id)
    party = _legacy_bad_party(db_session, fresh_org_id, state_code="GJ")
    inv = _draft(db_session, fresh_org_id, firm, item, party)
    # Simulate the pre-fix row shape.
    inv.tax_type = TaxType.NIL_NOT_A_SUPPLY.value
    inv.invoice_type = DocumentType.TAX_INVOICE.value
    inv.gst_amount = Decimal("0")
    db_session.flush()
    with pytest.raises(AppValidationError, match=r"(?i)place of supply"):
        sales_service.finalize_invoice(
            db_session, org_id=fresh_org_id, sales_invoice_id=inv.sales_invoice_id
        )


# ──────────────────────────────────────────────────────────────────────
# HTTP boundary
# ──────────────────────────────────────────────────────────────────────


def _signup_owner(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/auth/signup",
        json={
            "email": f"u-{uuid.uuid4().hex[:10]}@example.com",
            "password": "strong-password-1",
            "org_name": f"Org-{uuid.uuid4().hex[:8]}",
            "firm_name": "Primary",
            "state_code": "MH",
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body


def test_create_invoice_endpoint_422_for_bad_prefix_buyer(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    with OrmSession(sync_engine, expire_on_commit=False) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        firm = s.execute(select(Firm).where(Firm.firm_id == uuid.UUID(me["firm_id"]))).scalar_one()
        firm.state_code = "MH"
        firm.has_gst = True
        party = _legacy_bad_party(s, org_id)
        item = Item(
            org_id=org_id,
            code=f"I{uuid.uuid4().hex[:6]}",
            name="Chiffon",
            item_type=ItemType.FINISHED,
            tracking=TrackingType.NONE,
            primary_uom=UomType.METER,
        )
        s.add(item)
        s.flush()
        party_id, item_id = party.party_id, item.item_id
        s.commit()

    resp = http_client.post(
        "/invoices",
        headers={"Authorization": f"Bearer {me['access_token']}"},
        json={
            "firm_id": me["firm_id"],
            "party_id": str(party_id),
            "invoice_date": "2026-09-02",
            "lines": [{"item_id": str(item_id), "qty": "1", "price": "1000", "gst_rate": "5"}],
        },
    )
    assert resp.status_code == 422, resp.text
    assert "place of supply" in resp.text.lower()

    # Party API rejects the same GSTIN on create.
    bad = http_client.post(
        "/parties",
        headers={"Authorization": f"Bearer {me['access_token']}"},
        json={"code": "BADP", "name": "Bad P", "is_customer": True, "gstin": BAD_99},
    )
    assert bad.status_code == 422, bad.text
    assert "state code '99'" in bad.text


# ──────────────────────────────────────────────────────────────────────
# Read-only detection script
# ──────────────────────────────────────────────────────────────────────


def test_detection_script_lists_only_bad_prefix_parties(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    from scripts.detect_invalid_gstin_prefix import find_invalid_gstin_parties

    bad = _legacy_bad_party(db_session, fresh_org_id)
    _create(db_session, fresh_org_id, gstin=GOOD_MH)
    _create(db_session, fresh_org_id)  # no GSTIN
    found = find_invalid_gstin_parties(db_session, org_id=fresh_org_id)
    assert [f.party_id for f in found] == [bad.party_id]
    assert found[0].gstin == BAD_99
    assert "state code '99'" in found[0].error

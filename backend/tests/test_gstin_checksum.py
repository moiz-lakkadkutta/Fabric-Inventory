"""GSTIN check digit (15th character) — GSTN mod-36 over the first 14.

Before: only the format and the state prefix were checked; a typo anywhere
in the PAN part (or a transposition) was accepted and printed on invoices.

After: ``gstin_validation_error`` also checks the check digit. It runs
wherever that rule runs: party create, party update when the GSTIN changes
(an unchanged legacy GSTIN is left alone, #215 pattern), and the Vyapar
importer (an invalid GSTIN is dropped with a warning, party still imports).

The algorithm was checked against 15 real GSTINs (published registrations of
Reliance Industries and Infosys). PENDING MOIZ+CA SIGN-OFF.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError
from app.models import Party
from app.service import masters_service
from app.service.migration import VyaparExcelAdapter
from app.utils.crypto import decrypt_pii, encrypt_pii, get_org_dek
from app.utils.gst_states import gstin_check_digit, gstin_validation_error
from tests._gstin import make_gstin

# Real, publicly listed registrations (Reliance Industries Ltd, Infosys Ltd).
REAL_GSTINS = [
    # Non-company registrations (verifier cross-check, public listings):
    # state govt department, local authority, trust, AJP, partnership firm,
    # proprietor, HUF, and python-stdnum's own test vector.
    "37AAAGP3279H1Z1",
    "33AAALG7715L1Z1",
    "27AAATI1446A1Z7",
    "09AAAJI0396R1ZJ",
    "27AAGFS7543C1Z6",
    "07AAAHI0420G1ZY",
    "27AAPFU0939F1ZV",
    "27AAACR5055K1Z7",
    "27AAACR5055K2Z6",
    "27AAACR5055K3Z5",
    "27AAACR5055K4Z4",
    "27AAACR5055K5Z3",
    "29AAACI4798L1ZU",
    "29AAACI4798L2ZT",
    "29AAACI4798L3ZS",
    "29AAACI4798L4ZR",
    "32AAACI4798L3Z5",
    "36AAACI4798L3ZX",
    "09AAACI4798L2ZV",
    "21AAACI4798L1ZA",
    "21AAACI4798L3Z8",
    "07AAACI4798L1Z0",
]
CORRUPTED = [
    "27AAACR5055K1Z8",  # wrong check digit
    "29AAACI4798L1ZT",  # wrong check digit
    "27AAACR5505K1Z7",  # transposed PAN digits, original check digit
    "27AAACR5O55K1Z7",  # letter O typed for zero (format check catches it)
]
CHECKSUM_MSG = "GSTIN check digit doesn't match — please re-check the number"


@pytest.mark.parametrize("gstin", REAL_GSTINS)
def test_real_gstins_pass(gstin: str) -> None:
    assert gstin_check_digit(gstin[:14]) == gstin[14]
    assert gstin_validation_error(gstin) is None


@pytest.mark.parametrize("gstin", CORRUPTED[:3])
def test_corrupted_gstins_fail_with_actionable_message(gstin: str) -> None:
    err = gstin_validation_error(gstin)
    assert err is not None
    assert CHECKSUM_MSG in err
    assert gstin in err


def test_letter_for_digit_typo_is_rejected() -> None:
    # 'O' for '0' inside the PAN digits breaks the format before the checksum.
    assert gstin_validation_error(CORRUPTED[3]) is not None


def test_prefix_error_still_reported_before_checksum() -> None:
    err = gstin_validation_error(make_gstin("99"))
    assert err is not None and "state code '99'" in err


def test_test_helper_agrees_with_app() -> None:
    for g in REAL_GSTINS:
        assert make_gstin(g[:2], g[2:12], g[12]) == g


def _create(db_session: OrmSession, org_id: uuid.UUID, **kw: object) -> Party:
    return masters_service.create_party(
        db_session,
        org_id=org_id,
        firm_id=None,
        code=f"P{uuid.uuid4().hex[:6].upper()}",
        name="Checksum Test",
        is_customer=True,
        **kw,  # type: ignore[arg-type]
    )


def test_create_party_rejects_bad_check_digit(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    with pytest.raises(AppValidationError, match=CHECKSUM_MSG):
        _create(db_session, fresh_org_id, gstin="27AAACR5055K1Z8")


def test_create_party_accepts_real_gstin(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    party = _create(db_session, fresh_org_id, gstin="27aaacr5055k1z7 ")
    dek = get_org_dek(db_session, org_id=fresh_org_id)
    assert decrypt_pii(party.gstin, dek=dek, org_id=fresh_org_id) == "27AAACR5055K1Z7"


def test_update_party_rejects_changed_gstin_with_bad_check_digit(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    party = _create(db_session, fresh_org_id, gstin="27AAACR5055K1Z7")
    with pytest.raises(AppValidationError, match=CHECKSUM_MSG):
        masters_service.update_party(
            db_session, org_id=fresh_org_id, party_id=party.party_id, gstin="27AAACR5055K2Z7"
        )


def test_legacy_bad_checksum_party_resending_unchanged_gstin_still_works(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """A row stored before this rule keeps working: the edit form re-sends
    the unchanged GSTIN, which is not re-validated."""
    dek = get_org_dek(db_session, org_id=fresh_org_id)
    party = Party(
        org_id=fresh_org_id,
        code=f"L{uuid.uuid4().hex[:6].upper()}",
        name="Legacy Checksum",
        is_customer=True,
        gstin=encrypt_pii("27AAACR5055K1Z8", dek=dek, org_id=fresh_org_id),
    )
    db_session.add(party)
    db_session.flush()
    updated = masters_service.update_party(
        db_session,
        org_id=fresh_org_id,
        party_id=party.party_id,
        gstin="27aaacr5055k1z8",
        phone="9876543210",
    )
    assert decrypt_pii(updated.gstin, dek=dek, org_id=fresh_org_id) == "27AAACR5055K1Z8"
    assert decrypt_pii(updated.phone, dek=dek, org_id=fresh_org_id) == "9876543210"


def _vyapar_xlsx(gstin: str) -> bytes:
    from io import BytesIO

    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("Parties")
    ws.append(["Party Name", "GSTIN", "Type", "Opening Balance", "Balance Type"])
    ws.append(["Typo Traders", gstin, "Customer", "1000", "To Receive"])
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def test_vyapar_import_drops_bad_checksum_gstin_with_warning() -> None:
    src = _vyapar_xlsx("27AAACR5055K1Z8")
    adapter = VyaparExcelAdapter()
    msgs = [r.message for r in adapter.validate(src).rows if r.code == "GSTIN_FORMAT_INVALID"]
    assert msgs and CHECKSUM_MSG in msgs[0]
    parties = list(adapter.extract_parties(src))
    assert len(parties) == 1 and parties[0].gstin is None


def test_party_api_422_for_bad_check_digit(http_client: TestClient) -> None:
    resp = http_client.post(
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
    token = resp.json()["access_token"]
    bad = http_client.post(
        "/parties",
        headers={"Authorization": f"Bearer {token}"},
        json={"code": "CK1", "name": "Typo", "is_customer": True, "gstin": "27AAACR5055K1Z8"},
    )
    assert bad.status_code == 422, bad.text
    assert CHECKSUM_MSG in bad.json()["detail"]
    good = http_client.post(
        "/parties",
        headers={"Authorization": f"Bearer {token}"},
        json={"code": "CK2", "name": "Real", "is_customer": True, "gstin": "27AAACR5055K1Z7"},
    )
    assert good.status_code == 201, good.text

"""Masters service — Party CRUD (TASK-010).

Sync `Session`-based, kw-only signatures, RLS enforced at the DB layer
via the `app.current_org_id` GUC the dependency sets.

Encrypted columns (gstin, pan, phone) go through `app.utils.crypto`
helpers — stubs for MVP, swap-in target for Phase-2 envelope encryption.

Validations live in the service layer:
- GSTIN format (basic regex; full state-code + checksum check is TASK-047 GST engine).
- Code/name non-empty.
- Code uniqueness per (org, firm) — DB-enforced via
  `party_org_id_firm_id_code_key`; service catches early for clean 422.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError
from app.models import Party
from app.models.masters import TaxStatus
from app.utils.crypto import encrypt_pii

# Format check only — full GSTIN validation (state-code lookup, checksum
# digit, etc.) lives in TASK-047 GST engine. Here we just keep obvious
# garbage out at write time.
# GSTIN = 15 chars: 2 state + 5 PAN-letters + 4 PAN-digits + 1 PAN-letter
# + 1 entity-code (1-9 or A-Z) + literal Z + 1 checksum (alphanumeric).
_GSTIN_REGEX = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[A-Z\d]$")
_PAN_REGEX = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")


def _validate_gstin(gstin: str | None) -> None:
    if gstin is None or gstin == "":
        return
    if not _GSTIN_REGEX.fullmatch(gstin):
        raise AppValidationError(f"Invalid GSTIN format: {gstin!r}")


def _validate_pan(pan: str | None) -> None:
    if pan is None or pan == "":
        return
    if not _PAN_REGEX.fullmatch(pan):
        raise AppValidationError(f"Invalid PAN format: {pan!r}")


def create_party(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None,
    code: str,
    name: str,
    is_supplier: bool = False,
    is_customer: bool = False,
    is_karigar: bool = False,
    is_transporter: bool = False,
    tax_status: TaxStatus = TaxStatus.UNREGISTERED,
    gstin: str | None = None,
    pan: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    state_code: str | None = None,
    contact_person: str | None = None,
    legal_name: str | None = None,
    credit_limit: str | None = None,
    notes: str | None = None,
    created_by: uuid.UUID | None = None,
) -> Party:
    """Create a new Party. PII fields (gstin, pan, phone) are encrypted via
    the stub crypto helpers — column shape is `BYTEA` ready for real envelope
    encryption.
    """
    if not code:
        raise AppValidationError("Party code is required")
    if not name:
        raise AppValidationError("Party name is required")
    if not (is_supplier or is_customer or is_karigar or is_transporter):
        raise AppValidationError(
            "At least one party type flag must be true "
            "(is_supplier / is_customer / is_karigar / is_transporter)"
        )

    _validate_gstin(gstin)
    _validate_pan(pan)

    existing = session.execute(
        select(Party).where(
            Party.org_id == org_id,
            Party.firm_id.is_(firm_id) if firm_id is None else Party.firm_id == firm_id,
            Party.code == code,
            Party.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise AppValidationError(f"Party with code {code!r} already exists in this org/firm scope")

    party = Party(
        org_id=org_id,
        firm_id=firm_id,
        code=code,
        name=name,
        legal_name=legal_name,
        is_supplier=is_supplier,
        is_customer=is_customer,
        is_karigar=is_karigar,
        is_transporter=is_transporter,
        tax_status=tax_status,
        gstin=encrypt_pii(gstin),
        pan=encrypt_pii(pan),
        phone=encrypt_pii(phone),
        email=email,
        state_code=state_code,
        contact_person=contact_person,
        credit_limit=credit_limit,
        notes=notes,
        is_active=True,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(party)
    session.flush()
    return party


def get_party(session: Session, *, org_id: uuid.UUID, party_id: uuid.UUID) -> Party:
    """Fetch a single party by id. Raises `AppValidationError` if not found
    or soft-deleted.

    `org_id` is filtered explicitly here as defense-in-depth on top of RLS:
    even if a misconfigured connection bypasses RLS, the application
    layer still scopes the query to the caller's org. CLAUDE.md invariant.
    """
    party = session.execute(
        select(Party).where(
            Party.party_id == party_id,
            Party.org_id == org_id,
            Party.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if party is None:
        raise AppValidationError(f"Party {party_id} not found")
    return party


def list_parties(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    party_type: str | None = None,
    is_active: bool | None = True,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Party]:
    """List parties scoped by RLS GUC + explicit org_id filter + optional
    filters. The explicit `org_id` is defense-in-depth on top of RLS per
    CLAUDE.md invariant.

    `firm_id`:
      - `None`     → return ALL parties in the org (Owner / org-level view).
      - a UUID     → return parties with that firm_id OR firm_id IS NULL
        (org-level parties are visible to firm-scoped users by default).

    `party_type`: one of "supplier", "customer", "karigar", "transporter".
    Filters by the corresponding `is_*` boolean.

    `is_active`: when True (default), excludes inactive rows; pass None to
    include both.

    `search`: case-insensitive substring match on code or name.
    """
    stmt = select(Party).where(Party.org_id == org_id, Party.deleted_at.is_(None))

    if firm_id is not None:
        stmt = stmt.where(or_(Party.firm_id == firm_id, Party.firm_id.is_(None)))

    if is_active is True:
        stmt = stmt.where(Party.is_active.is_(True))
    elif is_active is False:
        stmt = stmt.where(Party.is_active.is_(False))

    if party_type is not None:
        type_map = {
            "supplier": Party.is_supplier,
            "customer": Party.is_customer,
            "karigar": Party.is_karigar,
            "transporter": Party.is_transporter,
        }
        if party_type not in type_map:
            raise AppValidationError(
                f"Invalid party_type {party_type!r}; expected one of {sorted(type_map)}"
            )
        stmt = stmt.where(type_map[party_type].is_(True))

    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(Party.code.ilike(like), Party.name.ilike(like)))

    stmt = stmt.order_by(Party.code).limit(limit).offset(offset)
    return list(session.execute(stmt).scalars())


def update_party(
    session: Session,
    *,
    org_id: uuid.UUID,
    party_id: uuid.UUID,
    name: str | None = None,
    legal_name: str | None = None,
    is_supplier: bool | None = None,
    is_customer: bool | None = None,
    is_karigar: bool | None = None,
    is_transporter: bool | None = None,
    tax_status: TaxStatus | None = None,
    gstin: str | None = None,
    pan: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    state_code: str | None = None,
    contact_person: str | None = None,
    credit_limit: str | None = None,
    notes: str | None = None,
    is_active: bool | None = None,
    updated_by: uuid.UUID | None = None,
) -> Party:
    """PATCH semantics — only fields explicitly passed are updated.

    Validates GSTIN/PAN format if changed. `code` is intentionally
    immutable (changing a code mid-flight breaks downstream references
    in invoices, ledgers, etc.) — re-create or rename via a separate
    workflow if ever needed.
    """
    party = get_party(session, org_id=org_id, party_id=party_id)

    if name is not None:
        if not name:
            raise AppValidationError("name cannot be empty")
        party.name = name
    if legal_name is not None:
        party.legal_name = legal_name
    if is_supplier is not None:
        party.is_supplier = is_supplier
    if is_customer is not None:
        party.is_customer = is_customer
    if is_karigar is not None:
        party.is_karigar = is_karigar
    if is_transporter is not None:
        party.is_transporter = is_transporter
    if tax_status is not None:
        party.tax_status = tax_status
    if gstin is not None:
        _validate_gstin(gstin if gstin != "" else None)
        party.gstin = encrypt_pii(gstin if gstin != "" else None)
    if pan is not None:
        _validate_pan(pan if pan != "" else None)
        party.pan = encrypt_pii(pan if pan != "" else None)
    if phone is not None:
        party.phone = encrypt_pii(phone if phone != "" else None)
    if email is not None:
        party.email = email if email != "" else None
    if state_code is not None:
        party.state_code = state_code if state_code != "" else None
    if contact_person is not None:
        party.contact_person = contact_person
    if credit_limit is not None:
        party.credit_limit = credit_limit
    if notes is not None:
        party.notes = notes
    if is_active is not None:
        party.is_active = is_active

    party.updated_at = datetime.now(tz=UTC)
    if updated_by is not None:
        party.updated_by = updated_by

    session.flush()
    return party


def soft_delete_party(
    session: Session,
    *,
    org_id: uuid.UUID,
    party_id: uuid.UUID,
    deleted_by: uuid.UUID | None = None,
) -> None:
    """Mark a party deleted. Idempotent: deleting an already-deleted party
    is a no-op success. `org_id` filters explicitly as defense-in-depth.
    """
    party = session.execute(
        select(Party).where(Party.party_id == party_id, Party.org_id == org_id)
    ).scalar_one_or_none()
    if party is None:
        raise AppValidationError(f"Party {party_id} not found")
    if party.deleted_at is not None:
        return  # already deleted
    party.deleted_at = datetime.now(tz=UTC)
    party.is_active = False
    if deleted_by is not None:
        party.updated_by = deleted_by
    session.flush()


__all__ = [
    "create_party",
    "get_party",
    "list_parties",
    "soft_delete_party",
    "update_party",
]

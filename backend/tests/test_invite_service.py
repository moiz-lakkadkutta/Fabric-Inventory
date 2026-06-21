"""IDM-2: firm-in-org guard on invite_service.create_invite (strict TDD).
PRIV-1 / IDM-1: permission ceiling on create_invite + change_user_role.

Tests:
  - foreign firm_id on create_invite → AppValidationError (RED target)
  - valid in-org firm_id → invite created (positive)
  - firm_id=None → invite created, no guard triggered (optional guard)
  - Vector B: invite ceiling — low-priv actor cannot invite into role w/ higher perms
  - Vector C: self-promotion block + change-role ceiling
"""

from __future__ import annotations

import contextlib
import uuid

import pytest
from sqlalchemy import select as _select
from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError, PermissionDeniedError
from app.models import AppUser, Firm, Organization, Role, UserRole
from app.service import identity_service, invite_service, rbac_service
from app.utils.crypto import generate_dek, wrap_dek

# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _make_foreign_firm(db: OrmSession) -> uuid.UUID:
    """Create a new org + firm, return the firm_id.
    GUC is left on the foreign org after return; callers must restore it.
    """
    foreign_org_id = uuid.uuid4()
    db.execute(text(f"SET LOCAL app.current_org_id = '{foreign_org_id}'"))
    db.add(
        Organization(
            org_id=foreign_org_id,
            name=f"foreign-invite-org-{foreign_org_id.hex[:8]}",
            admin_email=f"admin-{foreign_org_id.hex[:6]}@foreign.test",
            encrypted_dek=wrap_dek(generate_dek(), org_id=foreign_org_id),
        )
    )
    db.flush()
    foreign_firm = Firm(
        org_id=foreign_org_id,
        code=f"FF-{foreign_org_id.hex[:6]}",
        name="Foreign Invite Firm",
        has_gst=False,
    )
    db.add(foreign_firm)
    db.flush()
    return foreign_firm.firm_id


def _make_in_org_firm(db: OrmSession, org_id: uuid.UUID) -> uuid.UUID:
    """Create a Firm under org_id (GUC must already be set to org_id)."""
    firm = Firm(
        org_id=org_id,
        code=f"FI-{uuid.uuid4().hex[:6]}",
        name="In-Org Invite Firm",
        has_gst=False,
    )
    db.add(firm)
    db.flush()
    return firm.firm_id


def _get_role_id(db: OrmSession, org_id: uuid.UUID) -> uuid.UUID:
    """Return any live role_id belonging to org_id."""
    role = db.execute(
        __import__("sqlalchemy", fromlist=["select"])
        .select(Role)
        .where(
            Role.org_id == org_id,
            Role.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if role is None:
        # Mint a minimal role for testing.
        role = Role(
            org_id=org_id,
            code="SALESPERSON",
            name="Salesperson",
        )
        db.add(role)
        db.flush()
    return role.role_id


def _make_owner_user(db: OrmSession, org_id: uuid.UUID) -> uuid.UUID:
    """Create a real AppUser in the org so invited_by FK is satisfied."""
    user = identity_service.register_user(
        db,
        email=f"owner-{uuid.uuid4().hex[:8]}@test.local",
        password="TestPass123!",
        org_id=org_id,
    )
    return user.user_id


# ──────────────────────────────────────────────────────────────────────
# IDM-2 tests
# ──────────────────────────────────────────────────────────────────────


def test_create_invite_foreign_firm_id_raises(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """IDM-2: firm_id from another org passed to create_invite → AppValidationError."""
    role_id = _get_role_id(db_session, fresh_org_id)

    foreign_firm_id = _make_foreign_firm(db_session)
    # Restore GUC to the caller's org.
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{fresh_org_id}'"))

    with pytest.raises(AppValidationError, match=r"[Ff]irm"):
        invite_service.create_invite(
            db_session,
            org_id=fresh_org_id,
            invited_by=_make_owner_user(db_session, fresh_org_id),
            email=f"invitee-{uuid.uuid4().hex[:8]}@test.local",
            role_id=role_id,
            firm_id=foreign_firm_id,
        )


def test_create_invite_valid_in_org_firm_passes(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """IDM-2 positive: in-org firm_id → invite created without error."""
    role_id = _get_role_id(db_session, fresh_org_id)
    in_org_firm_id = _make_in_org_firm(db_session, fresh_org_id)

    result = invite_service.create_invite(
        db_session,
        org_id=fresh_org_id,
        invited_by=_make_owner_user(db_session, fresh_org_id),
        email=f"invitee-{uuid.uuid4().hex[:8]}@test.local",
        role_id=role_id,
        firm_id=in_org_firm_id,
    )
    assert result.invite_id is not None
    assert result.raw_token


def test_create_invite_none_firm_id_passes(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    """IDM-2: firm_id=None skips the guard entirely — invite is still created."""
    role_id = _get_role_id(db_session, fresh_org_id)

    result = invite_service.create_invite(
        db_session,
        org_id=fresh_org_id,
        invited_by=_make_owner_user(db_session, fresh_org_id),
        email=f"invitee-{uuid.uuid4().hex[:8]}@test.local",
        role_id=role_id,
        firm_id=None,
    )
    assert result.invite_id is not None
    assert result.raw_token


# ──────────────────────────────────────────────────────────────────────
# PRIV-1 / IDM-1 helpers
# ──────────────────────────────────────────────────────────────────────


def _seed_org_roles(db: OrmSession, org_id: uuid.UUID) -> dict[str, Role]:
    """Seed system roles for org_id and return {code: Role}."""
    return rbac_service.seed_system_roles(db, org_id=org_id)


def _make_user_with_role(
    db: OrmSession,
    org_id: uuid.UUID,
    role: Role,
) -> AppUser:
    """Create a new AppUser and assign role (org-level) using system path."""
    user = identity_service.register_user(
        db,
        email=f"u-{uuid.uuid4().hex[:10]}@test.local",
        password="TestPass123!",
        org_id=org_id,
    )
    rbac_service.assign_role(
        db,
        user_id=user.user_id,
        role_id=role.role_id,
        firm_id=None,
        org_id=org_id,
    )
    return user


def _make_low_priv_user(
    db: OrmSession,
    org_id: uuid.UUID,
    permission_codes: list[str],
    code_suffix: str = "",
) -> AppUser:
    """Create a custom role with permission_codes and a user assigned to it.
    Uses actor_user_id=None (seed path) to bypass ceiling on the role itself.
    """
    role = rbac_service.create_custom_role(
        db,
        org_id=org_id,
        code=f"LP_INVITE_ROLE{code_suffix}",
        name=f"LP Invite Role{code_suffix}",
        permission_codes=permission_codes,
        actor_user_id=None,  # system seed path
    )
    user = identity_service.register_user(
        db,
        email=f"lp-{uuid.uuid4().hex[:10]}@test.local",
        password="TestPass123!",
        org_id=org_id,
    )
    rbac_service.assign_role(
        db,
        user_id=user.user_id,
        role_id=role.role_id,
        firm_id=None,
        org_id=org_id,
    )
    return user


# ── Vector B: create_invite ceiling ──────────────────────────────────


def test_priv1_vector_b_create_invite_ceiling_blocks_owner_role_for_low_priv(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Vector B (PRIV-1): low-priv actor cannot invite someone into OWNER role
    because OWNER's permission set ⊄ actor's permissions.
    """
    roles = _seed_org_roles(db_session, fresh_org_id)
    # Actor has only admin.user.manage — cannot confer OWNER's full perm set
    actor = _make_low_priv_user(db_session, fresh_org_id, ["admin.user.manage"], "_B1")

    owner_role_id = roles["OWNER"].role_id

    with pytest.raises(PermissionDeniedError):
        invite_service.create_invite(
            db_session,
            org_id=fresh_org_id,
            invited_by=actor.user_id,
            email=f"target-{uuid.uuid4().hex[:8]}@test.local",
            role_id=owner_role_id,
            firm_id=None,
            actor_firm_id=None,
        )


def test_priv1_vector_b_owner_can_invite_into_any_role(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Vector B positive: Owner can invite someone into any role including OWNER."""
    roles = _seed_org_roles(db_session, fresh_org_id)
    owner = _make_user_with_role(db_session, fresh_org_id, roles["OWNER"])

    result = invite_service.create_invite(
        db_session,
        org_id=fresh_org_id,
        invited_by=owner.user_id,
        email=f"new-owner-{uuid.uuid4().hex[:8]}@test.local",
        role_id=roles["OWNER"].role_id,
        firm_id=None,
        actor_firm_id=None,
    )
    assert result.invite_id is not None


def test_priv1_vector_b_low_priv_can_invite_into_subset_role(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Vector B positive: low-priv actor CAN invite into a role whose perm set ⊆ actor's."""
    _seed_org_roles(db_session, fresh_org_id)
    # Actor has: masters.party.read + admin.user.manage
    actor = _make_low_priv_user(
        db_session, fresh_org_id, ["masters.party.read", "admin.user.manage"], "_B2"
    )
    # Invitee role has only masters.party.read ⊆ actor's perms → allowed
    invitee_role = rbac_service.create_custom_role(
        db_session,
        org_id=fresh_org_id,
        code="SUBSET_ROLE_INV",
        name="Subset Role Inv",
        permission_codes=["masters.party.read"],
        actor_user_id=None,
    )

    result = invite_service.create_invite(
        db_session,
        org_id=fresh_org_id,
        invited_by=actor.user_id,
        email=f"invitee-{uuid.uuid4().hex[:8]}@test.local",
        role_id=invitee_role.role_id,
        firm_id=None,
        actor_firm_id=None,
    )
    assert result.invite_id is not None


# ── Vector C: change_user_role ────────────────────────────────────────


def test_priv1_vector_c_self_promotion_blocked(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Vector C (PRIV-1): actor == target_user_id → PermissionDeniedError."""
    roles = _seed_org_roles(db_session, fresh_org_id)
    actor = _make_low_priv_user(db_session, fresh_org_id, ["admin.user.manage"], "_C1")
    owner_role = roles["OWNER"]

    with pytest.raises(PermissionDeniedError, match=r"[Oo]wn"):
        invite_service.change_user_role(
            db_session,
            org_id=fresh_org_id,
            actor_user_id=actor.user_id,
            target_user_id=actor.user_id,  # same as actor — self-promotion attempt
            new_role_id=owner_role.role_id,
            actor_firm_id=None,
        )


def test_priv1_vector_c_ceiling_blocks_promotion_to_higher_role(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Vector C (PRIV-1): low-priv actor cannot change another user's role to OWNER."""
    roles = _seed_org_roles(db_session, fresh_org_id)
    actor = _make_low_priv_user(db_session, fresh_org_id, ["admin.user.manage"], "_C2")
    target = _make_low_priv_user(db_session, fresh_org_id, ["masters.party.read"], "_C2T")

    with pytest.raises(PermissionDeniedError):
        invite_service.change_user_role(
            db_session,
            org_id=fresh_org_id,
            actor_user_id=actor.user_id,
            target_user_id=target.user_id,
            new_role_id=roles["OWNER"].role_id,
            actor_firm_id=None,
        )


def test_priv1_vector_c_owner_can_change_any_role(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Vector C positive: Owner can change a user's role to any role."""
    roles = _seed_org_roles(db_session, fresh_org_id)
    # Two owners so last-owner guard doesn't block demoting one
    owner1 = _make_user_with_role(db_session, fresh_org_id, roles["OWNER"])
    target = _make_user_with_role(db_session, fresh_org_id, roles["SALESPERSON"])

    # Owner promotes target to ACCOUNTANT — perms ⊆ Owner's → allowed
    invite_service.change_user_role(
        db_session,
        org_id=fresh_org_id,
        actor_user_id=owner1.user_id,
        target_user_id=target.user_id,
        new_role_id=roles["ACCOUNTANT"].role_id,
        actor_firm_id=None,
    )
    # Verify the target now has exactly one role
    new_roles = (
        db_session.execute(
            _select(UserRole).where(
                UserRole.user_id == target.user_id,
                UserRole.org_id == fresh_org_id,
            )
        )
        .scalars()
        .all()
    )
    assert len(new_roles) == 1


def test_priv1_idm1_end_to_end_low_priv_cannot_gain_elevated_perms(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """IDM-1 end-to-end: after ALL three blocked attempts the low-priv actor
    still has only their original permission set — no escalation occurred.
    """
    roles = _seed_org_roles(db_session, fresh_org_id)
    actor = _make_low_priv_user(
        db_session, fresh_org_id, ["identity.role.create", "admin.user.manage"], "_E2E"
    )
    target = _make_low_priv_user(db_session, fresh_org_id, ["masters.party.read"], "_E2ET")

    initial_perms = rbac_service.get_user_permissions(
        db_session, user_id=actor.user_id, firm_id=None
    )

    # Vector A: try to create a god-role (blocked by PRIV-1 fix)
    with contextlib.suppress(PermissionDeniedError):
        rbac_service.create_custom_role(
            db_session,
            org_id=fresh_org_id,
            code="GODMODE_E2E",
            name="God",
            permission_codes=["admin.firm.manage"],
            actor_user_id=actor.user_id,
            actor_firm_id=None,
        )

    # Vector B: try to invite into OWNER role (blocked by PRIV-1 fix)
    with contextlib.suppress(PermissionDeniedError):
        invite_service.create_invite(
            db_session,
            org_id=fresh_org_id,
            invited_by=actor.user_id,
            email=f"victim-{uuid.uuid4().hex[:6]}@test.local",
            role_id=roles["OWNER"].role_id,
            firm_id=None,
            actor_firm_id=None,
        )

    # Vector C-a: try self-promotion (blocked by PRIV-1 fix)
    with contextlib.suppress(PermissionDeniedError):
        invite_service.change_user_role(
            db_session,
            org_id=fresh_org_id,
            actor_user_id=actor.user_id,
            target_user_id=actor.user_id,
            new_role_id=roles["OWNER"].role_id,
            actor_firm_id=None,
        )

    # Vector C-b: try promoting another user to OWNER (blocked by PRIV-1 fix)
    with contextlib.suppress(PermissionDeniedError):
        invite_service.change_user_role(
            db_session,
            org_id=fresh_org_id,
            actor_user_id=actor.user_id,
            target_user_id=target.user_id,
            new_role_id=roles["OWNER"].role_id,
            actor_firm_id=None,
        )

    final_perms = rbac_service.get_user_permissions(db_session, user_id=actor.user_id, firm_id=None)
    assert final_perms == initial_perms, (
        f"IDM-1 violation: actor's perms changed after escalation attempts!\n"
        f"Before: {sorted(initial_perms)}\nAfter:  {sorted(final_perms)}"
    )

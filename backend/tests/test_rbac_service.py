"""TASK-009: RBAC service — seed system roles, permission checks, custom roles."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError, PermissionDeniedError
from app.models import AppUser, AuditLog, Firm, Permission, Role, RolePermission, UserRole
from app.service import rbac_service

# ──────────────────────────────────────────────────────────────────────
# Seeding
# ──────────────────────────────────────────────────────────────────────


def test_seed_permissions_creates_full_catalog(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    perms = rbac_service.seed_system_permissions(db_session, org_id=fresh_org_id)
    expected = {f"{r}.{a}" for r, a, _ in rbac_service._SYSTEM_PERMISSIONS}
    assert set(perms.keys()) == expected
    # Every row is flagged as system permission.
    rows = (
        db_session.execute(select(Permission).where(Permission.org_id == fresh_org_id))
        .scalars()
        .all()
    )
    assert all(p.is_system_permission for p in rows)
    assert len(rows) == len(expected)


def test_seed_permissions_is_idempotent(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    rbac_service.seed_system_permissions(db_session, org_id=fresh_org_id)
    first_count = db_session.execute(
        select(Permission).where(Permission.org_id == fresh_org_id)
    ).all()
    rbac_service.seed_system_permissions(db_session, org_id=fresh_org_id)
    second_count = db_session.execute(
        select(Permission).where(Permission.org_id == fresh_org_id)
    ).all()
    assert len(first_count) == len(second_count)


def test_seed_roles_creates_five_system_roles(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    roles = rbac_service.seed_system_roles(db_session, org_id=fresh_org_id)
    assert set(roles.keys()) == {
        "OWNER",
        "ACCOUNTANT",
        "SALESPERSON",
        "WAREHOUSE",
        "PRODUCTION_MANAGER",
    }
    for role in roles.values():
        assert role.is_system_role is True


def test_seed_roles_is_idempotent_no_dup_grants(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    rbac_service.seed_system_roles(db_session, org_id=fresh_org_id)
    rbac_service.seed_system_roles(db_session, org_id=fresh_org_id)
    role_count = len(db_session.execute(select(Role).where(Role.org_id == fresh_org_id)).all())
    grant_count = len(
        db_session.execute(
            select(RolePermission).where(RolePermission.org_id == fresh_org_id)
        ).all()
    )
    # 5 system roles only.
    assert role_count == 5
    # Owner grants are the entire catalog (38 rows). Total grants is the sum
    # over 5 roles. Run once; assert second seed didn't double it.
    expected_grants = sum(len(perms) for *_, perms in rbac_service._SYSTEM_ROLES)
    assert grant_count == expected_grants


# ──────────────────────────────────────────────────────────────────────
# Permission checks
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def seeded_org(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> tuple[uuid.UUID, dict[str, Role]]:
    roles = rbac_service.seed_system_roles(db_session, org_id=fresh_org_id)
    return fresh_org_id, roles


def _make_user(db_session: OrmSession, org_id: uuid.UUID) -> AppUser:
    user = AppUser(org_id=org_id, email=f"u-{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    db_session.flush()
    return user


def _make_firm(db_session: OrmSession, org_id: uuid.UUID, code: str) -> Firm:
    firm = Firm(org_id=org_id, code=code, name=f"Firm-{code}", has_gst=True)
    db_session.add(firm)
    db_session.flush()
    return firm


def test_owner_has_every_system_permission(
    db_session: OrmSession, seeded_org: tuple[uuid.UUID, dict[str, Role]]
) -> None:
    org_id, roles = seeded_org
    user = _make_user(db_session, org_id)
    rbac_service.assign_role(
        db_session,
        user_id=user.user_id,
        role_id=roles["OWNER"].role_id,
        firm_id=None,
        org_id=org_id,
    )
    perms = rbac_service.get_user_permissions(db_session, user_id=user.user_id, firm_id=None)
    assert perms == {f"{r}.{a}" for r, a, _ in rbac_service._SYSTEM_PERMISSIONS}


def test_accountant_has_voucher_post_but_not_invoice_create(
    db_session: OrmSession, seeded_org: tuple[uuid.UUID, dict[str, Role]]
) -> None:
    org_id, roles = seeded_org
    user = _make_user(db_session, org_id)
    rbac_service.assign_role(
        db_session,
        user_id=user.user_id,
        role_id=roles["ACCOUNTANT"].role_id,
        firm_id=None,
        org_id=org_id,
    )
    assert rbac_service.has_permission(
        db_session, user_id=user.user_id, firm_id=None, permission_code="accounting.voucher.post"
    )
    assert not rbac_service.has_permission(
        db_session, user_id=user.user_id, firm_id=None, permission_code="sales.invoice.create"
    )


def test_salesperson_has_invoice_perms_but_not_voucher_post(
    db_session: OrmSession, seeded_org: tuple[uuid.UUID, dict[str, Role]]
) -> None:
    org_id, roles = seeded_org
    user = _make_user(db_session, org_id)
    rbac_service.assign_role(
        db_session,
        user_id=user.user_id,
        role_id=roles["SALESPERSON"].role_id,
        firm_id=None,
        org_id=org_id,
    )
    perms = rbac_service.get_user_permissions(db_session, user_id=user.user_id, firm_id=None)
    assert "sales.invoice.create" in perms
    assert "sales.invoice.finalize" in perms
    assert "accounting.voucher.post" not in perms


def test_user_can_have_different_roles_in_different_firms(
    db_session: OrmSession, seeded_org: tuple[uuid.UUID, dict[str, Role]]
) -> None:
    """The plan/spec acceptance: per-firm role assignments."""
    org_id, roles = seeded_org
    firm_a = _make_firm(db_session, org_id, "FA")
    firm_b = _make_firm(db_session, org_id, "FB")
    user = _make_user(db_session, org_id)

    rbac_service.assign_role(
        db_session,
        user_id=user.user_id,
        role_id=roles["ACCOUNTANT"].role_id,
        firm_id=firm_a.firm_id,
        org_id=org_id,
    )
    rbac_service.assign_role(
        db_session,
        user_id=user.user_id,
        role_id=roles["SALESPERSON"].role_id,
        firm_id=firm_b.firm_id,
        org_id=org_id,
    )

    perms_a = rbac_service.get_user_permissions(
        db_session, user_id=user.user_id, firm_id=firm_a.firm_id
    )
    perms_b = rbac_service.get_user_permissions(
        db_session, user_id=user.user_id, firm_id=firm_b.firm_id
    )
    # Accountant has voucher.post in firm A, not in firm B.
    assert "accounting.voucher.post" in perms_a
    assert "accounting.voucher.post" not in perms_b
    # Salesperson has invoice.create in firm B, not in firm A.
    assert "sales.invoice.create" in perms_b
    assert "sales.invoice.create" not in perms_a


def test_org_level_role_applies_in_every_firm(
    db_session: OrmSession, seeded_org: tuple[uuid.UUID, dict[str, Role]]
) -> None:
    """firm_id=None means the role applies in any firm scope queried."""
    org_id, roles = seeded_org
    firm = _make_firm(db_session, org_id, "FA")
    user = _make_user(db_session, org_id)

    rbac_service.assign_role(
        db_session,
        user_id=user.user_id,
        role_id=roles["OWNER"].role_id,
        firm_id=None,
        org_id=org_id,
    )
    # Owner is org-level → has perms when querying firm_id=firm.firm_id too.
    assert rbac_service.has_permission(
        db_session, user_id=user.user_id, firm_id=firm.firm_id, permission_code="admin.firm.manage"
    )


def test_assign_role_is_idempotent(
    db_session: OrmSession, seeded_org: tuple[uuid.UUID, dict[str, Role]]
) -> None:
    org_id, roles = seeded_org
    user = _make_user(db_session, org_id)
    first = rbac_service.assign_role(
        db_session,
        user_id=user.user_id,
        role_id=roles["WAREHOUSE"].role_id,
        firm_id=None,
        org_id=org_id,
    )
    second = rbac_service.assign_role(
        db_session,
        user_id=user.user_id,
        role_id=roles["WAREHOUSE"].role_id,
        firm_id=None,
        org_id=org_id,
    )
    assert first.user_role_id == second.user_role_id


# ──────────────────────────────────────────────────────────────────────
# Custom roles
# ──────────────────────────────────────────────────────────────────────


def test_create_custom_role_succeeds(
    db_session: OrmSession, seeded_org: tuple[uuid.UUID, dict[str, Role]]
) -> None:
    org_id, _ = seeded_org
    role = rbac_service.create_custom_role(
        db_session,
        org_id=org_id,
        code="JUNIOR_ACCOUNTANT",
        name="Junior Accountant",
        permission_codes=[
            "accounting.voucher.read",
            "accounting.report.view",
            "masters.party.read",
        ],
        description="Read-only books access",
    )
    assert role.is_system_role is False
    assert role.code == "JUNIOR_ACCOUNTANT"
    grants = (
        db_session.execute(select(RolePermission).where(RolePermission.role_id == role.role_id))
        .scalars()
        .all()
    )
    assert len(grants) == 3


def test_create_custom_role_refuses_system_role_code(
    db_session: OrmSession, seeded_org: tuple[uuid.UUID, dict[str, Role]]
) -> None:
    org_id, _ = seeded_org
    with pytest.raises(AppValidationError, match="reserved for a system role"):
        rbac_service.create_custom_role(
            db_session,
            org_id=org_id,
            code="OWNER",
            name="My Owner",
            permission_codes=[],
        )


def test_create_custom_role_refuses_unknown_permissions(
    db_session: OrmSession, seeded_org: tuple[uuid.UUID, dict[str, Role]]
) -> None:
    org_id, _ = seeded_org
    with pytest.raises(AppValidationError, match="Unknown permission codes"):
        rbac_service.create_custom_role(
            db_session,
            org_id=org_id,
            code="ROGUE",
            name="Rogue",
            permission_codes=["world.dominate"],
        )


def test_create_custom_role_refuses_empty_code_or_name(
    db_session: OrmSession, seeded_org: tuple[uuid.UUID, dict[str, Role]]
) -> None:
    org_id, _ = seeded_org
    with pytest.raises(AppValidationError, match="`code` and `name`"):
        rbac_service.create_custom_role(
            db_session, org_id=org_id, code="", name="", permission_codes=[]
        )


def test_update_system_role_raises(
    db_session: OrmSession, seeded_org: tuple[uuid.UUID, dict[str, Role]]
) -> None:
    org_id, _ = seeded_org
    _ = org_id  # arg-only; the function never touches DB.
    with pytest.raises(PermissionDeniedError):
        rbac_service.update_system_role()


# ──────────────────────────────────────────────────────────────────────
# UserRole assignments don't leak across users
# ──────────────────────────────────────────────────────────────────────


def test_user_with_no_roles_has_no_permissions(
    db_session: OrmSession, seeded_org: tuple[uuid.UUID, dict[str, Role]]
) -> None:
    org_id, _ = seeded_org
    user = _make_user(db_session, org_id)
    perms = rbac_service.get_user_permissions(db_session, user_id=user.user_id, firm_id=None)
    assert perms == set()
    # Sanity: also no rows for them.
    rows = db_session.execute(select(UserRole).where(UserRole.user_id == user.user_id)).all()
    assert rows == []


# ──────────────────────────────────────────────────────────────────────
# CRYPTO-05: masters.party.pii.read permission catalog + role grants
# ──────────────────────────────────────────────────────────────────────


def test_pii_permission_in_catalog() -> None:
    """masters.party.pii.read must appear in the system permission catalog."""
    codes = {f"{r}.{a}" for r, a, _ in rbac_service._SYSTEM_PERMISSIONS}
    assert "masters.party.pii.read" in codes


def test_all_party_read_roles_in_catalog_get_pii_read() -> None:
    """Every role in _SYSTEM_ROLES that carries masters.party.read must also
    carry masters.party.pii.read so existing operators don't lose PII access.
    """
    for code, _name, _desc, perm_codes in rbac_service._SYSTEM_ROLES:
        if "masters.party.read" in perm_codes:
            assert "masters.party.pii.read" in perm_codes, (
                f"Role {code!r} has masters.party.read but NOT masters.party.pii.read — "
                "existing operators would silently lose PII access"
            )


# ──────────────────────────────────────────────────────────────────────
# CRYPTO-02: runtime RBAC mutations emit audit rows
# ──────────────────────────────────────────────────────────────────────


def test_assign_role_emits_audit_row(
    db_session: OrmSession, seeded_org: tuple[uuid.UUID, dict[str, Role]]
) -> None:
    """assign_role with actor_user_id must write an AuditLog row with action='role_assign'."""
    org_id, roles = seeded_org

    actor = AppUser(org_id=org_id, email=f"actor-{uuid.uuid4().hex[:6]}@x.com")
    target = AppUser(org_id=org_id, email=f"target-{uuid.uuid4().hex[:6]}@x.com")
    db_session.add_all([actor, target])
    db_session.flush()

    rbac_service.assign_role(
        db_session,
        user_id=target.user_id,
        role_id=roles["SALESPERSON"].role_id,
        firm_id=None,
        org_id=org_id,
        actor_user_id=actor.user_id,
    )
    db_session.flush()

    row = db_session.execute(
        select(AuditLog).where(
            AuditLog.org_id == org_id,
            AuditLog.action == "role_assign",
        )
    ).scalar_one_or_none()
    assert row is not None, "AuditLog row must exist after assign_role"
    assert row.user_id == actor.user_id
    assert row.entity_type == "UserRole"


def test_assign_role_no_audit_on_idempotent_noop(
    db_session: OrmSession, seeded_org: tuple[uuid.UUID, dict[str, Role]]
) -> None:
    """Second identical assign_role call (idempotent) must NOT emit a second audit row."""
    org_id, roles = seeded_org
    actor = AppUser(org_id=org_id, email=f"actor2-{uuid.uuid4().hex[:6]}@x.com")
    target = AppUser(org_id=org_id, email=f"target2-{uuid.uuid4().hex[:6]}@x.com")
    db_session.add_all([actor, target])
    db_session.flush()

    # First call — creates UserRole + audit row
    rbac_service.assign_role(
        db_session,
        user_id=target.user_id,
        role_id=roles["WAREHOUSE"].role_id,
        firm_id=None,
        org_id=org_id,
        actor_user_id=actor.user_id,
    )
    db_session.flush()

    # Second identical call — idempotent, must not add another audit row
    rbac_service.assign_role(
        db_session,
        user_id=target.user_id,
        role_id=roles["WAREHOUSE"].role_id,
        firm_id=None,
        org_id=org_id,
        actor_user_id=actor.user_id,
    )
    db_session.flush()

    rows = (
        db_session.execute(
            select(AuditLog).where(
                AuditLog.org_id == org_id,
                AuditLog.action == "role_assign",
                AuditLog.user_id == actor.user_id,
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, f"Expected exactly 1 audit row, got {len(rows)}"


# ──────────────────────────────────────────────────────────────────────
# PRIV-1 / IDM-1: Vector A — permission ceiling on create/update custom role
# ──────────────────────────────────────────────────────────────────────


def _make_low_priv_actor_with_role_perms(
    db_session: OrmSession,
    org_id: uuid.UUID,
    permission_codes: list[str],
    code_suffix: str = "",
) -> uuid.UUID:
    """Create a custom role with the given permission_codes, create a user,
    assign them that role (org-level, firm_id=None), return user_id.
    Uses actor_user_id=None (system/seed path) to create the role itself.
    """
    role = rbac_service.create_custom_role(
        db_session,
        org_id=org_id,
        code=f"LP_TEST_ROLE{code_suffix}",
        name=f"LP Test Role{code_suffix}",
        permission_codes=permission_codes,
        actor_user_id=None,  # seed path — no ceiling check
    )
    user = _make_user(db_session, org_id)
    rbac_service.assign_role(
        db_session,
        user_id=user.user_id,
        role_id=role.role_id,
        firm_id=None,
        org_id=org_id,
    )
    return user.user_id


def test_priv1_vector_a_create_role_ceiling_blocks_low_priv(
    db_session: OrmSession, seeded_org: tuple[uuid.UUID, dict[str, Role]]
) -> None:
    """PRIV-1 Vector A: actor cannot mint a role containing perms they don't hold."""
    org_id, _ = seeded_org
    actor_id = _make_low_priv_actor_with_role_perms(
        db_session, org_id, ["identity.role.create", "admin.user.manage"]
    )

    with pytest.raises(PermissionDeniedError):
        rbac_service.create_custom_role(
            db_session,
            org_id=org_id,
            code="ESCALATION_ROLE",
            name="Escalation Role",
            # admin.firm.manage is NOT in actor's {identity.role.create, admin.user.manage}
            permission_codes=["identity.role.create", "admin.firm.manage"],
            actor_user_id=actor_id,
            actor_firm_id=None,
        )


def test_priv1_vector_a_update_role_ceiling_blocks_low_priv(
    db_session: OrmSession, seeded_org: tuple[uuid.UUID, dict[str, Role]]
) -> None:
    """PRIV-1 Vector A: actor cannot update a role to include perms they lack."""
    org_id, _ = seeded_org
    actor_id = _make_low_priv_actor_with_role_perms(
        db_session, org_id, ["identity.role.create", "admin.user.manage"], "_UPD"
    )

    target_role = rbac_service.create_custom_role(
        db_session,
        org_id=org_id,
        code="TARGET_ESCALATION",
        name="Target Escalation",
        permission_codes=["masters.party.read"],
        actor_user_id=None,
    )

    with pytest.raises(PermissionDeniedError):
        rbac_service.update_custom_role(
            db_session,
            org_id=org_id,
            role_id=target_role.role_id,
            permission_codes=["identity.role.create", "admin.firm.manage"],
            actor_user_id=actor_id,
            actor_firm_id=None,
        )


def test_priv1_vector_a_owner_can_create_role_with_any_perm(
    db_session: OrmSession, seeded_org: tuple[uuid.UUID, dict[str, Role]]
) -> None:
    """PRIV-1 positive: Owner (all perms) can create a role with any permissions."""
    org_id, roles = seeded_org
    owner_user = _make_user(db_session, org_id)
    rbac_service.assign_role(
        db_session,
        user_id=owner_user.user_id,
        role_id=roles["OWNER"].role_id,
        firm_id=None,
        org_id=org_id,
    )

    role = rbac_service.create_custom_role(
        db_session,
        org_id=org_id,
        code="OWNER_FULL_ROLE",
        name="Owner Full Role",
        permission_codes=["admin.firm.manage", "accounting.period.close"],
        actor_user_id=owner_user.user_id,
        actor_firm_id=None,
    )
    assert role.code == "OWNER_FULL_ROLE"


def test_priv1_vector_a_system_path_skips_ceiling(
    db_session: OrmSession, seeded_org: tuple[uuid.UUID, dict[str, Role]]
) -> None:
    """System bootstrap path (actor_user_id=None) bypasses the ceiling — seed must work."""
    org_id, _ = seeded_org
    role = rbac_service.create_custom_role(
        db_session,
        org_id=org_id,
        code="SYSTEM_SEED_ROLE",
        name="System Seed",
        permission_codes=["admin.firm.manage"],
        actor_user_id=None,
    )
    assert role.code == "SYSTEM_SEED_ROLE"


def test_priv1_vector_a_owner_can_update_role_with_any_perm(
    db_session: OrmSession, seeded_org: tuple[uuid.UUID, dict[str, Role]]
) -> None:
    """PRIV-1 positive: Owner can update a role to include any perm."""
    org_id, roles = seeded_org
    owner_user = _make_user(db_session, org_id)
    rbac_service.assign_role(
        db_session,
        user_id=owner_user.user_id,
        role_id=roles["OWNER"].role_id,
        firm_id=None,
        org_id=org_id,
    )

    target_role = rbac_service.create_custom_role(
        db_session,
        org_id=org_id,
        code="TARGET_FOR_OWNER_UPDATE",
        name="Target For Owner Update",
        permission_codes=["masters.party.read"],
        actor_user_id=None,
    )

    updated = rbac_service.update_custom_role(
        db_session,
        org_id=org_id,
        role_id=target_role.role_id,
        permission_codes=["admin.firm.manage", "accounting.period.close"],
        actor_user_id=owner_user.user_id,
        actor_firm_id=None,
    )
    assert updated.role_id == target_role.role_id

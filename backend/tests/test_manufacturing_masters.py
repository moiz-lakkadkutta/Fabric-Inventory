"""TASK-TR-A02: Manufacturing masters (Design / Operation Master / Cost Centre)
CRUD integration tests.

Each test signs up a fresh org via the auth router (which seeds RBAC +
creates an Owner user + Primary firm), then exercises the new
``/designs``, ``/operation-masters`` and ``/cost-centres`` endpoints
with that owner's JWT.

Covers: auth, permission gates, validation, PATCH semantics, soft-delete,
cross-org isolation at the HTTP layer.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession


def _signup_owner(client: TestClient) -> dict[str, str]:
    """Create a fresh org + Owner user + Primary firm; return tokens + ids."""
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


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_second_firm_in_org(
    sync_engine: Engine,
    *,
    org_id: uuid.UUID,
    code: str = "SECOND",
    name: str = "Second Firm",
) -> str:
    """Insert a SECOND firm in the SAME org so cross-firm scope checks
    can be exercised (mirrors the helper in test_bom / test_routing).
    """
    from app.models import Firm

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        firm = Firm(
            org_id=org_id,
            code=code,
            name=name,
            has_gst=False,
            state_code="MH",
        )
        session.add(firm)
        session.flush()
        firm_id = str(firm.firm_id)
        session.commit()
    return firm_id


def _make_salesperson(
    sync_engine: Engine,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
) -> str:
    """Provision a SALESPERSON user in `org_id` and return their access token.

    Mirrors `test_reports_routers.test_reports_require_accounting_report_view_permission`.
    """
    from sqlalchemy import select

    from app.models import AppUser, Role
    from app.service import identity_service, rbac_service

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        sales_role = session.execute(
            select(Role).where(Role.org_id == org_id, Role.code == "SALESPERSON")
        ).scalar_one()
        sales_user = identity_service.register_user(
            session,
            email=f"sales-{uuid.uuid4().hex[:6]}@example.com",
            password="strong-password-1",
            org_id=org_id,
        )
        rbac_service.assign_role(
            session,
            user_id=sales_user.user_id,
            role_id=sales_role.role_id,
            firm_id=firm_id,
            org_id=org_id,
        )
        sales_user_id = sales_user.user_id
        session.commit()

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        sales_user = session.execute(
            select(AppUser).where(AppUser.user_id == sales_user_id)
        ).scalar_one()
        pair = identity_service.issue_tokens(session, user=sales_user, firm_id=firm_id)
        session.commit()
    return pair.access_token


# ──────────────────────────────────────────────────────────────────────
# /designs — Design CRUD
# ──────────────────────────────────────────────────────────────────────


def test_create_design_returns_201(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/designs",
        headers=_auth(me["access_token"]),
        json={
            "code": "D-001",
            "name": "Anarkali — Embroidered",
            "firm_id": me["firm_id"],
            "description": "3-piece anarkali; gold thread embroidery.",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == "D-001"
    assert body["name"] == "Anarkali — Embroidered"
    assert body["org_id"] == me["org_id"]
    assert body["firm_id"] == me["firm_id"]


def test_create_design_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.post(
        "/designs",
        json={"code": "D-X", "name": "X", "firm_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 401


def test_create_design_with_empty_code_returns_422(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/designs",
        headers=_auth(me["access_token"]),
        json={"code": "", "name": "X", "firm_id": me["firm_id"]},
    )
    assert resp.status_code == 422


def test_create_design_duplicate_code_returns_422(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    http_client.post(
        "/designs",
        headers=_auth(me["access_token"]),
        json={"code": "DUP", "name": "First", "firm_id": me["firm_id"]},
    ).raise_for_status()
    resp = http_client.post(
        "/designs",
        headers=_auth(me["access_token"]),
        json={"code": "DUP", "name": "Second", "firm_id": me["firm_id"]},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_get_design_returns_design(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    create = http_client.post(
        "/designs",
        headers=_auth(me["access_token"]),
        json={"code": "D-GET", "name": "X", "firm_id": me["firm_id"]},
    ).json()
    design_id = create["design_id"]
    resp = http_client.get(f"/designs/{design_id}", headers=_auth(me["access_token"]))
    assert resp.status_code == 200
    assert resp.json()["design_id"] == design_id
    assert resp.json()["code"] == "D-GET"


def test_get_design_cross_org_returns_422(http_client: TestClient) -> None:
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)
    other = http_client.post(
        "/designs",
        headers=_auth(me_b["access_token"]),
        json={"code": "B-DESIGN", "name": "B's design", "firm_id": me_b["firm_id"]},
    ).json()
    resp = http_client.get(f"/designs/{other['design_id']}", headers=_auth(me_a["access_token"]))
    assert resp.status_code == 422


def test_list_designs_filters_by_caller_org(http_client: TestClient) -> None:
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)
    http_client.post(
        "/designs",
        headers=_auth(me_a["access_token"]),
        json={"code": "A-D", "name": "A", "firm_id": me_a["firm_id"]},
    ).raise_for_status()
    http_client.post(
        "/designs",
        headers=_auth(me_b["access_token"]),
        json={"code": "B-D", "name": "B", "firm_id": me_b["firm_id"]},
    ).raise_for_status()

    resp = http_client.get("/designs", headers=_auth(me_a["access_token"]))
    assert resp.status_code == 200
    codes = {d["code"] for d in resp.json()["items"]}
    assert "A-D" in codes
    assert "B-D" not in codes


def test_patch_design_updates_name(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    create = http_client.post(
        "/designs",
        headers=_auth(me["access_token"]),
        json={"code": "D-UPD", "name": "Old", "firm_id": me["firm_id"]},
    ).json()
    did = create["design_id"]
    resp = http_client.patch(
        f"/designs/{did}",
        headers=_auth(me["access_token"]),
        json={"name": "New", "description": "Updated description"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "New"
    assert resp.json()["description"] == "Updated description"
    # code is immutable.
    assert resp.json()["code"] == "D-UPD"


def test_delete_design_soft_deletes_and_hides_from_list(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    create = http_client.post(
        "/designs",
        headers=_auth(me["access_token"]),
        json={"code": "D-DEL", "name": "X", "firm_id": me["firm_id"]},
    ).json()
    did = create["design_id"]
    resp = http_client.delete(f"/designs/{did}", headers=_auth(me["access_token"]))
    assert resp.status_code == 204
    listed = http_client.get("/designs", headers=_auth(me["access_token"])).json()
    assert all(d["code"] != "D-DEL" for d in listed["items"])


# ──────────────────────────────────────────────────────────────────────
# /operation-masters — OperationMaster CRUD
# ──────────────────────────────────────────────────────────────────────


def test_create_operation_master_returns_201(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/operation-masters",
        headers=_auth(me["access_token"]),
        json={
            "code": "OP-CUT",
            "name": "Cutting",
            "firm_id": me["firm_id"],
            "operation_type": "STITCHING",
            "default_duration_mins": "30.00",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == "OP-CUT"
    assert body["operation_type"] == "STITCHING"
    assert body["default_duration_mins"] == "30.00"
    assert body["is_active"] is True


def test_create_operation_master_invalid_type_returns_422(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/operation-masters",
        headers=_auth(me["access_token"]),
        json={
            "code": "OP-BAD",
            "name": "X",
            "firm_id": me["firm_id"],
            "operation_type": "NOT_AN_OP_TYPE",
        },
    )
    assert resp.status_code == 422


def test_get_operation_master(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    create = http_client.post(
        "/operation-masters",
        headers=_auth(me["access_token"]),
        json={"code": "OP-GET", "name": "X", "firm_id": me["firm_id"]},
    ).json()
    op_id = create["operation_master_id"]
    resp = http_client.get(f"/operation-masters/{op_id}", headers=_auth(me["access_token"]))
    assert resp.status_code == 200
    assert resp.json()["operation_master_id"] == op_id


def test_list_operation_masters_filters_by_caller_org(http_client: TestClient) -> None:
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)
    http_client.post(
        "/operation-masters",
        headers=_auth(me_a["access_token"]),
        json={"code": "A-OP", "name": "A", "firm_id": me_a["firm_id"]},
    ).raise_for_status()
    http_client.post(
        "/operation-masters",
        headers=_auth(me_b["access_token"]),
        json={"code": "B-OP", "name": "B", "firm_id": me_b["firm_id"]},
    ).raise_for_status()

    resp = http_client.get("/operation-masters", headers=_auth(me_a["access_token"]))
    codes = {o["code"] for o in resp.json()["items"]}
    assert "A-OP" in codes and "B-OP" not in codes


def test_patch_operation_master(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    create = http_client.post(
        "/operation-masters",
        headers=_auth(me["access_token"]),
        json={"code": "OP-UPD", "name": "Old", "firm_id": me["firm_id"]},
    ).json()
    op_id = create["operation_master_id"]
    resp = http_client.patch(
        f"/operation-masters/{op_id}",
        headers=_auth(me["access_token"]),
        json={"name": "New", "operation_type": "QC", "is_active": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "New"
    assert resp.json()["operation_type"] == "QC"
    assert resp.json()["is_active"] is False


def test_delete_operation_master(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    create = http_client.post(
        "/operation-masters",
        headers=_auth(me["access_token"]),
        json={"code": "OP-DEL", "name": "X", "firm_id": me["firm_id"]},
    ).json()
    op_id = create["operation_master_id"]
    resp = http_client.delete(f"/operation-masters/{op_id}", headers=_auth(me["access_token"]))
    assert resp.status_code == 204
    listed = http_client.get("/operation-masters", headers=_auth(me["access_token"])).json()
    assert all(o["code"] != "OP-DEL" for o in listed["items"])


# ──────────────────────────────────────────────────────────────────────
# /cost-centres — CostCentre CRUD
# ──────────────────────────────────────────────────────────────────────


def test_create_cost_centre_returns_201(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/cost-centres",
        headers=_auth(me["access_token"]),
        json={
            "code": "CC-CUT",
            "name": "Cutting Department",
            "firm_id": me["firm_id"],
            "cost_centre_type": "DEPARTMENT",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == "CC-CUT"
    assert body["cost_centre_type"] == "DEPARTMENT"


def test_create_cost_centre_duplicate_code_returns_422(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    http_client.post(
        "/cost-centres",
        headers=_auth(me["access_token"]),
        json={"code": "DUP-CC", "name": "First", "firm_id": me["firm_id"]},
    ).raise_for_status()
    resp = http_client.post(
        "/cost-centres",
        headers=_auth(me["access_token"]),
        json={"code": "DUP-CC", "name": "Second", "firm_id": me["firm_id"]},
    )
    assert resp.status_code == 422


def test_get_cost_centre(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    create = http_client.post(
        "/cost-centres",
        headers=_auth(me["access_token"]),
        json={"code": "CC-GET", "name": "X", "firm_id": me["firm_id"]},
    ).json()
    cc_id = create["cost_centre_id"]
    resp = http_client.get(f"/cost-centres/{cc_id}", headers=_auth(me["access_token"]))
    assert resp.status_code == 200
    assert resp.json()["cost_centre_id"] == cc_id


def test_list_cost_centres_filters_by_caller_org(http_client: TestClient) -> None:
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)
    http_client.post(
        "/cost-centres",
        headers=_auth(me_a["access_token"]),
        json={"code": "A-CC", "name": "A", "firm_id": me_a["firm_id"]},
    ).raise_for_status()
    http_client.post(
        "/cost-centres",
        headers=_auth(me_b["access_token"]),
        json={"code": "B-CC", "name": "B", "firm_id": me_b["firm_id"]},
    ).raise_for_status()

    resp = http_client.get("/cost-centres", headers=_auth(me_a["access_token"]))
    codes = {c["code"] for c in resp.json()["items"]}
    assert "A-CC" in codes and "B-CC" not in codes


def test_patch_cost_centre(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    create = http_client.post(
        "/cost-centres",
        headers=_auth(me["access_token"]),
        json={"code": "CC-UPD", "name": "Old", "firm_id": me["firm_id"]},
    ).json()
    cc_id = create["cost_centre_id"]
    resp = http_client.patch(
        f"/cost-centres/{cc_id}",
        headers=_auth(me["access_token"]),
        json={"name": "New", "cost_centre_type": "CHANNEL", "is_active": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "New"
    assert resp.json()["cost_centre_type"] == "CHANNEL"
    assert resp.json()["is_active"] is False


def test_delete_cost_centre(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    create = http_client.post(
        "/cost-centres",
        headers=_auth(me["access_token"]),
        json={"code": "CC-DEL", "name": "X", "firm_id": me["firm_id"]},
    ).json()
    cc_id = create["cost_centre_id"]
    resp = http_client.delete(f"/cost-centres/{cc_id}", headers=_auth(me["access_token"]))
    assert resp.status_code == 204
    listed = http_client.get("/cost-centres", headers=_auth(me["access_token"])).json()
    assert all(c["code"] != "CC-DEL" for c in listed["items"])


# ──────────────────────────────────────────────────────────────────────
# Permission gates — Salesperson role
# ──────────────────────────────────────────────────────────────────────


def test_salesperson_can_read_design_and_operation_master_but_not_cost_centre(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Per A02 RBAC spec: Salesperson reads `manufacturing.design.read` +
    `manufacturing.operation_master.read` (they need to look up designs +
    operations when quoting), but has NO access to cost-centres (financial
    classification — Accountant / Owner only).
    """
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    firm_id = uuid.UUID(me["firm_id"])

    # Owner seeds one of each entity.
    http_client.post(
        "/designs",
        headers=_auth(me["access_token"]),
        json={"code": "D-PERM", "name": "X", "firm_id": me["firm_id"]},
    ).raise_for_status()
    http_client.post(
        "/operation-masters",
        headers=_auth(me["access_token"]),
        json={"code": "OP-PERM", "name": "X", "firm_id": me["firm_id"]},
    ).raise_for_status()
    http_client.post(
        "/cost-centres",
        headers=_auth(me["access_token"]),
        json={"code": "CC-PERM", "name": "X", "firm_id": me["firm_id"]},
    ).raise_for_status()

    sales_token = _make_salesperson(sync_engine, org_id=org_id, firm_id=firm_id)

    # Read works for design + operation-master.
    r1 = http_client.get("/designs", headers=_auth(sales_token))
    assert r1.status_code == 200, r1.text
    r2 = http_client.get("/operation-masters", headers=_auth(sales_token))
    assert r2.status_code == 200, r2.text

    # Read is denied for cost-centre.
    r3 = http_client.get("/cost-centres", headers=_auth(sales_token))
    assert r3.status_code == 403, r3.text
    assert r3.json()["code"] == "PERMISSION_DENIED"


def test_salesperson_cannot_create_design(http_client: TestClient, sync_engine: Engine) -> None:
    """Salesperson has read but no write on manufacturing.design."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    firm_id = uuid.UUID(me["firm_id"])

    sales_token = _make_salesperson(sync_engine, org_id=org_id, firm_id=firm_id)
    resp = http_client.post(
        "/designs",
        headers=_auth(sales_token),
        json={"code": "D-NOPE", "name": "X", "firm_id": me["firm_id"]},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "PERMISSION_DENIED"


# ──────────────────────────────────────────────────────────────────────
# A02 hardening — cost_centre_id cross-org / cross-firm validation
# ──────────────────────────────────────────────────────────────────────
#
# Originally the service blindly accepted whatever `cost_centre_id` the
# caller supplied. A user in org A could pass a cost_centre_id belonging
# to org B (or to a different firm inside the same org) and have it land
# on their Design / OperationMaster row, breaking RLS semantics on every
# subsequent read.
#
# These tests pin the org-membership + firm-scope validation on every
# create / patch path that accepts an FK to `cost_centre`.


def test_create_design_rejects_cost_centre_from_different_org(
    http_client: TestClient,
) -> None:
    """Caller in org A supplies a cost_centre_id from org B → 422."""
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)

    # Org B creates a cost centre.
    cc_b = http_client.post(
        "/cost-centres",
        headers=_auth(me_b["access_token"]),
        json={"code": "CC-B-XORG", "name": "B-only", "firm_id": me_b["firm_id"]},
    ).json()

    # Org A tries to attach B's cost centre to a new design.
    resp = http_client.post(
        "/designs",
        headers=_auth(me_a["access_token"]),
        json={
            "code": "D-XORG",
            "name": "X",
            "firm_id": me_a["firm_id"],
            "cost_centre_id": cc_b["cost_centre_id"],
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_create_design_rejects_cost_centre_from_different_firm(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Same org, different firm: cost centres are firm-scoped, so the
    create must reject a CC that lives in a sibling firm."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    firm_b_id = _create_second_firm_in_org(sync_engine, org_id=org_id, code="DESIGN-XF1")

    # CC lives in firm B.
    cc_b = http_client.post(
        "/cost-centres",
        headers=_auth(me["access_token"]),
        json={"code": "CC-FIRM-B", "name": "Firm B CC", "firm_id": firm_b_id},
    ).json()

    # Try to create a design in firm A pointing at firm B's CC.
    resp = http_client.post(
        "/designs",
        headers=_auth(me["access_token"]),
        json={
            "code": "D-XFIRM",
            "name": "X",
            "firm_id": me["firm_id"],
            "cost_centre_id": cc_b["cost_centre_id"],
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_create_operation_master_rejects_cost_centre_from_different_org(
    http_client: TestClient,
) -> None:
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)
    cc_b = http_client.post(
        "/cost-centres",
        headers=_auth(me_b["access_token"]),
        json={"code": "CC-B-OP", "name": "B-only", "firm_id": me_b["firm_id"]},
    ).json()
    resp = http_client.post(
        "/operation-masters",
        headers=_auth(me_a["access_token"]),
        json={
            "code": "OP-XORG",
            "name": "X",
            "firm_id": me_a["firm_id"],
            "cost_centre_id": cc_b["cost_centre_id"],
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_create_operation_master_rejects_cost_centre_from_different_firm(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    firm_b_id = _create_second_firm_in_org(sync_engine, org_id=org_id, code="OP-XF1")
    cc_b = http_client.post(
        "/cost-centres",
        headers=_auth(me["access_token"]),
        json={"code": "CC-FB-OP", "name": "Firm B CC", "firm_id": firm_b_id},
    ).json()
    resp = http_client.post(
        "/operation-masters",
        headers=_auth(me["access_token"]),
        json={
            "code": "OP-XFIRM",
            "name": "X",
            "firm_id": me["firm_id"],
            "cost_centre_id": cc_b["cost_centre_id"],
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_patch_design_rejects_cost_centre_from_different_org(
    http_client: TestClient,
) -> None:
    """PATCH path must reapply the same FK ownership check as create."""
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)
    design_a = http_client.post(
        "/designs",
        headers=_auth(me_a["access_token"]),
        json={"code": "D-PATCH-XORG", "name": "X", "firm_id": me_a["firm_id"]},
    ).json()
    cc_b = http_client.post(
        "/cost-centres",
        headers=_auth(me_b["access_token"]),
        json={"code": "CC-B-PD", "name": "B-only", "firm_id": me_b["firm_id"]},
    ).json()
    resp = http_client.patch(
        f"/designs/{design_a['design_id']}",
        headers=_auth(me_a["access_token"]),
        json={"cost_centre_id": cc_b["cost_centre_id"]},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_patch_design_rejects_cost_centre_from_different_firm(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    firm_b_id = _create_second_firm_in_org(sync_engine, org_id=org_id, code="PD-XF1")
    design_a = http_client.post(
        "/designs",
        headers=_auth(me["access_token"]),
        json={"code": "D-PATCH-XFIRM", "name": "X", "firm_id": me["firm_id"]},
    ).json()
    cc_b = http_client.post(
        "/cost-centres",
        headers=_auth(me["access_token"]),
        json={"code": "CC-FB-PD", "name": "Firm B CC", "firm_id": firm_b_id},
    ).json()
    resp = http_client.patch(
        f"/designs/{design_a['design_id']}",
        headers=_auth(me["access_token"]),
        json={"cost_centre_id": cc_b["cost_centre_id"]},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_patch_operation_master_rejects_cost_centre_from_different_org(
    http_client: TestClient,
) -> None:
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)
    op_a = http_client.post(
        "/operation-masters",
        headers=_auth(me_a["access_token"]),
        json={"code": "OP-PATCH-XORG", "name": "X", "firm_id": me_a["firm_id"]},
    ).json()
    cc_b = http_client.post(
        "/cost-centres",
        headers=_auth(me_b["access_token"]),
        json={"code": "CC-B-POP", "name": "B-only", "firm_id": me_b["firm_id"]},
    ).json()
    resp = http_client.patch(
        f"/operation-masters/{op_a['operation_master_id']}",
        headers=_auth(me_a["access_token"]),
        json={"cost_centre_id": cc_b["cost_centre_id"]},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_patch_operation_master_rejects_cost_centre_from_different_firm(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    firm_b_id = _create_second_firm_in_org(sync_engine, org_id=org_id, code="POP-XF1")
    op_a = http_client.post(
        "/operation-masters",
        headers=_auth(me["access_token"]),
        json={"code": "OP-PATCH-XFIRM", "name": "X", "firm_id": me["firm_id"]},
    ).json()
    cc_b = http_client.post(
        "/cost-centres",
        headers=_auth(me["access_token"]),
        json={"code": "CC-FB-POP", "name": "Firm B CC", "firm_id": firm_b_id},
    ).json()
    resp = http_client.patch(
        f"/operation-masters/{op_a['operation_master_id']}",
        headers=_auth(me["access_token"]),
        json={"cost_centre_id": cc_b["cost_centre_id"]},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "VALIDATION_ERROR"


# `patch_cost_centre` already validates `parent_cost_centre_id` org-scope
# (see service code in `manufacturing_masters_service.patch_cost_centre`)
# but the firm-scope check was missing — a sibling firm's CC could be
# adopted as parent. Pin that here.
def test_patch_cost_centre_rejects_parent_from_different_firm(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    firm_b_id = _create_second_firm_in_org(sync_engine, org_id=org_id, code="CC-PAR-X")
    cc_a = http_client.post(
        "/cost-centres",
        headers=_auth(me["access_token"]),
        json={"code": "CC-A-CHILD", "name": "A child", "firm_id": me["firm_id"]},
    ).json()
    cc_b = http_client.post(
        "/cost-centres",
        headers=_auth(me["access_token"]),
        json={"code": "CC-B-PARENT", "name": "B parent", "firm_id": firm_b_id},
    ).json()
    resp = http_client.patch(
        f"/cost-centres/{cc_a['cost_centre_id']}",
        headers=_auth(me["access_token"]),
        json={"parent_cost_centre_id": cc_b["cost_centre_id"]},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_create_cost_centre_rejects_parent_from_different_firm(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    firm_b_id = _create_second_firm_in_org(sync_engine, org_id=org_id, code="CC-CRE-X")
    parent_b = http_client.post(
        "/cost-centres",
        headers=_auth(me["access_token"]),
        json={"code": "CC-B-PCC", "name": "B parent", "firm_id": firm_b_id},
    ).json()
    resp = http_client.post(
        "/cost-centres",
        headers=_auth(me["access_token"]),
        json={
            "code": "CC-CHILD-XFIRM",
            "name": "Child",
            "firm_id": me["firm_id"],
            "parent_cost_centre_id": parent_b["cost_centre_id"],
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "VALIDATION_ERROR"

"""TASK-TR-C1: signup must seed a default Location for the new firm.

A fresh-signup firm with zero Locations strands the user on every
"pick a location" dropdown — inventory list, GRN create, stock-issue,
etc. — and there is no FE path to create one on a brand-new org.

This test pins the contract: after `/auth/signup` returns 201, the new
firm has at least one active Location row. The signup wiring re-uses
`inventory_service.get_or_create_default_location`, so the seeded row
matches what `add_stock` lazily produces (code='MAIN', type=WAREHOUSE)
— that keeps the implicit contract from inventory_service intact.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.models import Location
from app.models.inventory import LocationType


def _unique_email() -> str:
    return f"u-{uuid.uuid4().hex[:10]}@example.com"


def _unique_org_name() -> str:
    return f"Org {uuid.uuid4().hex[:8]}"


def test_signup_seeds_default_location_for_new_firm(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Happy path: signup → at least one Location row for the firm."""
    resp = http_client.post(
        "/auth/signup",
        json={
            "email": _unique_email(),
            "password": "strong-password-1",
            "org_name": _unique_org_name(),
            "firm_name": "Primary Firm",
            "state_code": "MH",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    org_id = uuid.UUID(body["org_id"])
    firm_id = uuid.UUID(body["firm_id"])

    with OrmSession(sync_engine, expire_on_commit=False) as s:
        # GUC required under `fabric_app` (NOBYPASSRLS) — Location is
        # tenant-scoped so the read needs the org context set first.
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        rows = (
            s.execute(
                select(Location).where(Location.org_id == org_id, Location.firm_id == firm_id)
            )
            .scalars()
            .all()
        )

    assert len(rows) >= 1, "expected ≥1 Location to be seeded on signup"
    # Spot-check the default row's shape so a future refactor that
    # accidentally drops `WAREHOUSE` (or sets `is_active=false`) fails
    # loudly here rather than at the first inventory action.
    default = next((r for r in rows if r.code == "MAIN"), None)
    assert default is not None, "expected a Location with code='MAIN'"
    assert default.location_type == LocationType.WAREHOUSE
    assert default.is_active is True

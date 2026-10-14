"""Q01-02 regression guard — firm scope enforced on EVERY route.

Walks ``main.app.routes`` (the live route table, a superset of
``docs/reviews/security/q01-appendix/firm-scope-matrix.csv``) so a route added
later is covered without editing this file:

1. **Structural.** Every route is either on the explicit public /
   authenticated-only allowlist or carries a ``require_permission`` dependency
   — the one place the firm check lives. A new route with neither fails.
2. **Explicit firm targets (BODY / QUERY rows).** A user holding EVERY
   permission, but only in firm F1, sends each permission-guarded route
   ``?firm_id=<F2>`` (and ``{"firm_id": <F2>}`` as the JSON body of mutating
   methods). Every single route must answer 403 "No access to that firm" —
   proof the permission is authorised in the TARGET firm, not just the org.
3. **By-id rows (no firm in the request).** F2 resources are seeded by the
   Owner; every route whose only path parameter names one of them is called
   by the same F1-only user. Each must answer exactly as for an id that
   does not exist (invisible, like a cross-org id) and never succeed. The resource is re-read by
   the Owner afterwards to prove it is unchanged.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy.engine import Engine

from tests.security._q01_helpers import (
    add_sibling_firm,
    bearer,
    create_role,
    idem,
    invite_and_accept,
    login,
    q01_client,
    signup,
)

# Routes that legitimately carry no permission (public or authenticated-only
# by design — Q01 §4 lists the same 14). Anything else MUST use
# require_permission.
_NO_PERMISSION_ROUTES = {
    ("POST", "/auth/signup"),
    ("POST", "/auth/login"),
    ("POST", "/auth/mfa-verify"),
    ("POST", "/auth/mfa/setup"),
    ("POST", "/auth/mfa/confirm"),
    ("POST", "/auth/refresh"),
    ("POST", "/auth/logout"),
    ("POST", "/auth/switch-firm"),
    ("GET", "/auth/me"),
    ("POST", "/auth/forgot"),
    ("POST", "/auth/reset"),
    ("POST", "/admin/invites/accept"),
    ("GET", "/live"),
    ("GET", "/ready"),
}

_FIRM_DENIED_TITLE = "No access to that firm"
# Media types FastAPI decodes as a JSON body (fastapi/routing.py: maintype
# "application" and subtype "json" or "*+json", parsed case-insensitively).
# None = the header omitted entirely: FastAPI then parses the body as JSON too.
_JSON_CONTENT_TYPES: tuple[str | None, ...] = (
    None,
    "application/json",
    "Application/JSON; charset=utf-8",
    "application/vnd.api+json",
)


def _uses_require_permission(route: APIRoute) -> bool:
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        qualname = getattr(dep.call, "__qualname__", "")
        if qualname.startswith("require_permission."):
            return True
        stack.extend(dep.dependencies)
    return False


def _routes() -> list[tuple[str, str, APIRoute]]:
    from main import create_app

    app = create_app()
    out = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            out.append((method, route.path, route))
    return out


def test_q01_02_every_route_is_permission_guarded_or_allowlisted() -> None:
    unguarded = {
        (m, p)
        for m, p, r in _routes()
        if not _uses_require_permission(r) and (m, p) not in _NO_PERMISSION_ROUTES
    }
    assert unguarded == set(), (
        "routes without require_permission (the firm-scope chokepoint): "
        f"{sorted(unguarded)} — add a permission or justify an allowlist entry"
    )
    stale = _NO_PERMISSION_ROUTES - {(m, p) for m, p, _ in _routes()}
    assert stale == set(), f"allowlist entries for routes that no longer exist: {stale}"


def _fill_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", lambda _m: str(uuid.uuid4()), path)


async def _all_permission_codes(client: AsyncClient, owner_token: str) -> list[str]:
    resp = await client.get("/admin/permissions", headers=bearer(owner_token))
    assert resp.status_code == 200, resp.text
    return sorted({p["code"] for m in resp.json()["items"] for p in m["permissions"]})


async def _f1_superuser(client: AsyncClient, sync_engine: Engine) -> dict[str, Any]:
    """Org with F1 + F2; a user holding EVERY permission, granted in F1 only."""
    owner = await signup(client)
    f1 = owner["firm_id"]
    f2 = str(add_sibling_firm(sync_engine, uuid.UUID(owner["org_id"])))
    codes = await _all_permission_codes(client, owner["access_token"])
    role_id = await create_role(client, owner["access_token"], "q01_f1_all", codes)
    email = await invite_and_accept(
        client, inviter_token=owner["access_token"], role_id=role_id, firm_id=f1
    )
    session = await login(client, email=email, org_name=owner["_org_name"])
    assert session["firm_id"] == f1, session  # single granted firm → auto-selected
    me = await client.get("/auth/me", headers=bearer(session["access_token"]))
    assert set(me.json()["permissions"]) == set(codes)
    return {"owner": owner, "f1": f1, "f2": f2, "token": session["access_token"]}


async def test_q01_02_every_guarded_route_refuses_an_ungranted_firm_target(
    sync_engine: Engine,
) -> None:
    async with q01_client() as client:
        ctx = await _f1_superuser(client, sync_engine)
        wrong: dict[str, str] = {}
        checked = 0
        for method, path, route in _routes():
            if not _uses_require_permission(route):
                continue
            # Every way a request can name the firm must be caught on its own:
            # the query string, and (writes) a body-only JSON firm_id under
            # each media type FastAPI parses as JSON (B2: case variants and
            # application/*+json must not slip past the check).
            variants: list[tuple[str, dict[str, Any]]] = [
                ("query", {"params": {"firm_id": ctx["f2"]}, "headers": bearer(ctx["token"])})
            ]
            if method in {"POST", "PUT", "PATCH", "DELETE"}:
                for ctype in _JSON_CONTENT_TYPES:
                    headers = {**bearer(ctx["token"]), **idem()}
                    if ctype is not None:
                        headers["Content-Type"] = ctype
                    variants.append(
                        (
                            f"body[{ctype or 'no Content-Type'}]",
                            {"headers": headers, "content": json.dumps({"firm_id": ctx["f2"]})},
                        )
                    )
                variants[0][1]["headers"] = {**variants[0][1]["headers"], **idem()}
            for label, kwargs in variants:
                resp = await client.request(method, _fill_path(path), **kwargs)
                checked += 1
                try:
                    title = resp.json().get("title")
                except ValueError:
                    title = None
                if resp.status_code != 403 or title != _FIRM_DENIED_TITLE:
                    wrong[f"{method} {path} via {label}"] = f"{resp.status_code} {resp.text[:120]}"
        assert checked >= 150, f"route walk looks vacuous: only {checked} routes"
        assert wrong == {}, f"routes that did not refuse an ungranted firm_id: {wrong}"


async def _seed_f2_resources(client: AsyncClient, owner_token: str, f2: str) -> dict[str, str]:
    h = {**bearer(owner_token)}
    tag = uuid.uuid4().hex[:6].upper()
    out: dict[str, str] = {}

    async def post(path: str, body: dict[str, Any], key: str) -> None:
        resp = await client.post(path, headers={**h, **idem()}, json=body)
        assert resp.status_code == 201, f"{path}: {resp.text}"
        out[key] = str(resp.json()[key])

    await post(
        "/parties",
        {"code": f"P{tag}", "name": f"F2 party {tag}", "is_customer": True, "firm_id": f2},
        "party_id",
    )
    await post(
        "/items",
        {
            "code": f"I{tag}",
            "name": f"F2 item {tag}",
            "item_type": "FINISHED",
            "primary_uom": "METER",
            "firm_id": f2,
        },
        "item_id",
    )
    return out


_BY_ID_PARAMS = {"party_id", "item_id"}


async def test_q01_02_by_id_routes_hide_ungranted_firm_resources(sync_engine: Engine) -> None:
    async with q01_client() as client:
        ctx = await _f1_superuser(client, sync_engine)
        owner_token = ctx["owner"]["access_token"]
        seeded = await _seed_f2_resources(client, owner_token, ctx["f2"])
        before = {
            k: (
                await client.get(
                    f"/{'parties' if k == 'party_id' else 'items'}/{v}", headers=bearer(owner_token)
                )
            ).json()
            for k, v in seeded.items()
        }
        wrong: dict[str, str] = {}
        checked = 0
        for method, path, route in _routes():
            params = re.findall(r"\{([^}]+)\}", path)
            if len(params) != 1 or params[0] not in _BY_ID_PARAMS:
                continue
            if not _uses_require_permission(route):
                continue
            results = []
            for rid in (seeded[params[0]], str(uuid.uuid4())):
                kwargs: dict[str, Any] = {"headers": bearer(ctx["token"])}
                if method in {"POST", "PUT", "PATCH", "DELETE"}:
                    kwargs["headers"] = {**kwargs["headers"], **idem()}
                    if method != "DELETE":
                        kwargs["json"] = {"name": "hijacked"}
                resp = await client.request(
                    method, path.replace("{" + params[0] + "}", rid), **kwargs
                )
                results.append((resp.status_code, resp.text))
            checked += 1
            # Invisible == indistinguishable from an id that doesn't exist.
            (hidden, hidden_txt), (absent, _) = results
            if hidden < 400 or hidden != absent:
                wrong[f"{method} {path}"] = f"{hidden} vs nonexistent {absent}: {hidden_txt[:120]}"
        assert checked >= 6, f"by-id walk looks vacuous: {checked}"
        assert wrong == {}, f"F2 resources reachable by an F1-only user: {wrong}"
        after = {
            k: (
                await client.get(
                    f"/{'parties' if k == 'party_id' else 'items'}/{v}", headers=bearer(owner_token)
                )
            ).json()
            for k, v in seeded.items()
        }
        assert after == before, "an F2 resource was modified by an F1-only user"

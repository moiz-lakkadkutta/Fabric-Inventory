"""RBAC follow-up hardening (verifier findings on fu/rbac).

1. Two concurrent Owner demotions must never leave an org with zero Owners
   (the last-Owner guard is serialized per org by an advisory lock).
2. Editing / deleting a role needs the actor to outrank the role's CURRENT
   permissions (the Q01-05 rule applied to PATCH/DELETE /admin/roles/{id}).
3. A role delete racing an assignment of that role: never both succeed
   (the role row is locked FOR UPDATE on both paths).
4. Minor: soft-deleted users don't block a role delete; the outrank 403 never
   names another firm.

Races use real threads, ``threading.Barrier`` and separate sessions.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
import uuid
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import PermissionDeniedError
from app.models import AppUser, Role, UserRole
from app.service import invite_service, rbac_service
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


def _uid(engine: Engine, org_id: str, email: str) -> uuid.UUID:
    with OrmSession(engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        return s.execute(select(AppUser.user_id).where(AppUser.email == email)).scalar_one()


def _rid(engine: Engine, org_id: str, code: str) -> uuid.UUID:
    with OrmSession(engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        return s.execute(
            select(Role.role_id).where(Role.org_id == uuid.UUID(str(org_id)), Role.code == code)
        ).scalar_one()


def _owner_count(engine: Engine, org_id: str) -> int:
    with OrmSession(engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        return int(
            s.execute(
                text(
                    "SELECT count(DISTINCT ur.user_id) FROM user_role ur "
                    "JOIN role r ON r.role_id = ur.role_id "
                    "WHERE r.code = 'OWNER' AND ur.org_id = :o"
                ),
                {"o": str(org_id)},
            ).scalar_one()
        )


async def _two_owners(engine: Engine) -> tuple[str, uuid.UUID, uuid.UUID]:
    async with q01_client() as c:
        o = await signup(c)
        org = str(o["org_id"])
        e2 = await invite_and_accept(
            c,
            inviter_token=o["access_token"],
            role_id=str(_rid(engine, org, "OWNER")),
            firm_id=None,
        )
    return org, uuid.UUID(str(o["user_id"])), _uid(engine, org, e2)


def _race_role_changes(
    engine: Engine,
    org: str,
    jobs: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]],
    *,
    pause_after_guard: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    """Run change_user_role jobs on parallel threads (one session each). With
    ``pause_after_guard`` every thread that passes the last-Owner guard parks
    at a barrier so all would have read before any writes — if the guard
    isn't serialized. When it is, the barrier times out and the waiters go on."""
    after_guard = threading.Barrier(len(jobs), timeout=3)
    start = threading.Barrier(len(jobs), timeout=5)
    results = [""] * len(jobs)
    real_guard = invite_service.assert_not_last_owner

    def guard(*a: Any, **kw: Any) -> None:
        real_guard(*a, **kw)
        if pause_after_guard:
            with contextlib.suppress(threading.BrokenBarrierError):
                after_guard.wait()

    monkeypatch.setattr(invite_service, "assert_not_last_owner", guard)

    def worker(i: int, actor: uuid.UUID, target: uuid.UUID, new_role: uuid.UUID) -> None:
        try:
            with OrmSession(engine) as s:
                s.execute(text(f"SET LOCAL app.current_org_id = '{org}'"))
                start.wait()
                invite_service.change_user_role(
                    s,
                    org_id=uuid.UUID(org),
                    actor_user_id=actor,
                    target_user_id=target,
                    new_role_id=new_role,
                )
                s.commit()
                results[i] = "ok"
        except Exception as e:
            results[i] = type(e).__name__

    threads = [threading.Thread(target=worker, args=(i, *j)) for i, j in enumerate(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    return results


# Both Owners demoted to the SAME role also contend on that role's row lock
# (`_assignable_role` … FOR UPDATE), which alone serializes them. Demotions to
# DIFFERENT roles lock different rows, so only the per-org advisory lock
# (`lock_org_role_changes`) stands between them and a zero-Owner org.
ROLE_MIXES = {
    "same_role": ("ACCOUNTANT", "ACCOUNTANT"),
    "different_roles": ("ACCOUNTANT", "SALESPERSON"),
}


@pytest.mark.parametrize("pause_after_guard", [False, True])
@pytest.mark.parametrize("direction", ["demote_each_other", "both_self_demote"])
@pytest.mark.parametrize("role_mix", sorted(ROLE_MIXES))
async def test_concurrent_owner_demotions_leave_exactly_one_owner(
    sync_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    pause_after_guard: bool,
    direction: str,
    role_mix: str,
) -> None:
    org, a, b = await _two_owners(sync_engine)
    r1, r2 = (_rid(sync_engine, org, code) for code in ROLE_MIXES[role_mix])
    jobs = (
        [(a, b, r1), (b, a, r2)] if direction == "demote_each_other" else [(a, a, r1), (b, b, r2)]
    )
    results = _race_role_changes(
        sync_engine, org, jobs, pause_after_guard=pause_after_guard, monkeypatch=monkeypatch
    )
    # Exactly one wins. The loser hits the last-Owner guard (422), or, when
    # it was the one demoted first, no longer holds admin.user.manage (403).
    assert _owner_count(sync_engine, org) == 1, results
    assert results.count("ok") == 1, results
    loser = next(r for r in results if r != "ok")
    expected = (
        {"AppValidationError", "PermissionDeniedError"}
        if direction == "demote_each_other"
        else {"AppValidationError"}
    )
    assert loser in expected, results


@pytest.mark.parametrize("direction", ["demote_each_other", "both_self_demote"])
@pytest.mark.parametrize("role_mix", sorted(ROLE_MIXES))
async def test_concurrent_owner_demotions_over_http_never_zero_owners(
    sync_engine: Engine, direction: str, role_mix: str
) -> None:
    for _ in range(3):  # signup is rate-limited to 3 per test
        async with q01_client() as c:
            o = await signup(c)
            org = str(o["org_id"])
            e2 = await invite_and_accept(
                c,
                inviter_token=o["access_token"],
                role_id=str(_rid(sync_engine, org, "OWNER")),
                firm_id=None,
            )
            t2 = (await login(c, email=e2, org_name=o["_org_name"]))["access_token"]
            a = str(o["user_id"])
            b = str(_uid(sync_engine, org, e2))
            ra, rb = (str(_rid(sync_engine, org, code)) for code in ROLE_MIXES[role_mix])
            # (token, target, new role) for each of the two concurrent PATCHes.
            if direction == "demote_each_other":
                calls = [(o["access_token"], b, ra), (t2, a, rb)]
            else:
                calls = [(o["access_token"], a, ra), (t2, b, rb)]
            resps = await asyncio.gather(
                *[
                    c.patch(
                        f"/admin/users/{target}/role",
                        headers={**bearer(tok), **idem()},
                        json={"role_id": role},
                    )
                    for tok, target, role in calls
                ]
            )
            assert _owner_count(sync_engine, org) == 1, [r.text for r in resps]
            codes = sorted(r.status_code for r in resps)
            # The loser hits the last-Owner guard (422), or, if the winner
            # demoted it first, its stale token (401) or its lost
            # admin.user.manage (403).
            assert codes in ([204, 401], [204, 403], [204, 422]), [r.text for r in resps]


# ── role delete vs role assignment ─────────────────────────────────────


async def _role_pair_and_target(engine: Engine) -> dict[str, Any]:
    async with q01_client() as c:
        o = await signup(c)
        org = str(o["org_id"])
        ot = o["access_token"]
        r_old = await create_role(c, ot, f"ro_{uuid.uuid4().hex[:6]}", ["masters.party.read"])
        r_new = await create_role(c, ot, f"rn_{uuid.uuid4().hex[:6]}", ["masters.party.read"])
        email = await invite_and_accept(c, inviter_token=ot, role_id=r_old, firm_id=None)
    return {
        "org": org,
        "owner": uuid.UUID(str(o["user_id"])),
        "target": _uid(engine, org, email),
        "r_old": uuid.UUID(r_old),
        "r_new": uuid.UUID(r_new),
    }


def _final_state(engine: Engine, ctx: dict[str, Any]) -> tuple[list[uuid.UUID], bool]:
    with OrmSession(engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{ctx['org']}'"))
        held = list(
            s.execute(select(UserRole.role_id).where(UserRole.user_id == ctx["target"])).scalars()
        )
        deleted = (
            s.execute(select(Role.deleted_at).where(Role.role_id == ctx["r_new"])).scalar_one()
            is not None
        )
    return held, deleted


async def test_role_delete_waits_for_an_in_flight_assignment(
    sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Assigner validates the role first; the delete must then see the new
    assignment and refuse (422), not delete the role under the user."""
    ctx = await _role_pair_and_target(sync_engine)
    gate = threading.Barrier(2, timeout=5)
    res = ["", ""]
    real = invite_service._assignable_role

    def assignable_then_pause(*a: Any, **kw: Any) -> Role:
        role = real(*a, **kw)
        gate.wait()
        time.sleep(0.3)  # let the deleter reach its lock
        return role

    monkeypatch.setattr(invite_service, "_assignable_role", assignable_then_pause)

    def deleter() -> None:
        try:
            with OrmSession(sync_engine) as s:
                s.execute(text(f"SET LOCAL app.current_org_id = '{ctx['org']}'"))
                gate.wait()
                rbac_service.delete_custom_role(
                    s,
                    org_id=uuid.UUID(ctx["org"]),
                    role_id=ctx["r_new"],
                    actor_user_id=ctx["owner"],
                )
                s.commit()
                res[0] = "deleted"
        except Exception as e:
            res[0] = type(e).__name__

    def assigner() -> None:
        try:
            with OrmSession(sync_engine) as s:
                s.execute(text(f"SET LOCAL app.current_org_id = '{ctx['org']}'"))
                invite_service.change_user_role(
                    s,
                    org_id=uuid.UUID(ctx["org"]),
                    actor_user_id=ctx["owner"],
                    target_user_id=ctx["target"],
                    new_role_id=ctx["r_new"],
                )
                s.commit()
                res[1] = "assigned"
        except Exception as e:
            res[1] = type(e).__name__

    ts = [threading.Thread(target=deleter), threading.Thread(target=assigner)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(20)
    held, deleted = _final_state(sync_engine, ctx)
    assert res == ["AppValidationError", "assigned"], res
    assert held == [ctx["r_new"]] and not deleted


async def test_assignment_waits_for_an_in_flight_role_delete(sync_engine: Engine) -> None:
    """Deleter locks + soft-deletes first; the assignment must then see the
    deleted role and refuse (422), keeping the user on their old role."""
    ctx = await _role_pair_and_target(sync_engine)
    deleted_uncommitted = threading.Event()
    res = ["", ""]

    def deleter() -> None:
        try:
            with OrmSession(sync_engine) as s:
                s.execute(text(f"SET LOCAL app.current_org_id = '{ctx['org']}'"))
                rbac_service.delete_custom_role(
                    s,
                    org_id=uuid.UUID(ctx["org"]),
                    role_id=ctx["r_new"],
                    actor_user_id=ctx["owner"],
                )
                deleted_uncommitted.set()
                time.sleep(0.5)  # the assigner is now blocked on the row lock
                s.commit()
                res[0] = "deleted"
        except Exception as e:
            res[0] = type(e).__name__

    def assigner() -> None:
        deleted_uncommitted.wait(5)
        try:
            with OrmSession(sync_engine) as s:
                s.execute(text(f"SET LOCAL app.current_org_id = '{ctx['org']}'"))
                invite_service.change_user_role(
                    s,
                    org_id=uuid.UUID(ctx["org"]),
                    actor_user_id=ctx["owner"],
                    target_user_id=ctx["target"],
                    new_role_id=ctx["r_new"],
                )
                s.commit()
                res[1] = "assigned"
        except Exception as e:
            res[1] = type(e).__name__

    ts = [threading.Thread(target=deleter), threading.Thread(target=assigner)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(20)
    held, deleted = _final_state(sync_engine, ctx)
    assert res == ["deleted", "AppValidationError"], res
    assert held == [ctx["r_old"]] and deleted


# ── role edit / delete outrank rule ────────────────────────────────────


async def _role_editor_and_superior_role(client: Any, *, assign_big: bool) -> dict[str, Any]:
    o = await signup(client)
    ot = o["access_token"]
    big = await create_role(
        client, ot, f"big_{uuid.uuid4().hex[:6]}", ["accounting.voucher.post", "masters.party.read"]
    )
    ed = await create_role(
        client,
        ot,
        f"ed_{uuid.uuid4().hex[:6]}",
        [
            "identity.role.update",
            "identity.role.delete",
            "identity.role.read",
            "masters.party.read",
        ],
    )
    if assign_big:
        await invite_and_accept(client, inviter_token=ot, role_id=big, firm_id=None)
    ed_email = await invite_and_accept(client, inviter_token=ot, role_id=ed, firm_id=None)
    et = (await login(client, email=ed_email, org_name=o["_org_name"]))["access_token"]
    small = await create_role(client, ot, f"sm_{uuid.uuid4().hex[:6]}", ["masters.party.read"])
    return {"big": big, "small": small, "editor_token": et}


async def test_role_editor_cannot_strip_a_role_held_by_a_superior(sync_engine: Engine) -> None:
    _ = sync_engine
    async with q01_client() as c:
        ctx = await _role_editor_and_superior_role(c, assign_big=True)
        r = await c.patch(
            f"/admin/roles/{ctx['big']}",
            headers={**bearer(ctx["editor_token"]), **idem()},
            json={"permissions": ["masters.party.read"]},
        )
        assert r.status_code == 403, r.text
        assert "accounting.voucher.post" in r.json()["detail"]
        # Renaming it is an edit too.
        r = await c.patch(
            f"/admin/roles/{ctx['big']}",
            headers={**bearer(ctx["editor_token"]), **idem()},
            json={"name": "Renamed"},
        )
        assert r.status_code == 403, r.text


async def test_role_editor_cannot_delete_a_role_beyond_them(sync_engine: Engine) -> None:
    _ = sync_engine
    async with q01_client() as c:
        ctx = await _role_editor_and_superior_role(c, assign_big=False)
        r = await c.delete(
            f"/admin/roles/{ctx['big']}", headers={**bearer(ctx["editor_token"]), **idem()}
        )
        assert r.status_code == 403, r.text


async def test_role_editor_can_still_edit_and_delete_roles_within_them(
    sync_engine: Engine,
) -> None:
    _ = sync_engine
    async with q01_client() as c:
        ctx = await _role_editor_and_superior_role(c, assign_big=False)
        r = await c.patch(
            f"/admin/roles/{ctx['small']}",
            headers={**bearer(ctx["editor_token"]), **idem()},
            json={"permissions": []},
        )
        assert r.status_code == 200, r.text
        r = await c.delete(
            f"/admin/roles/{ctx['small']}", headers={**bearer(ctx["editor_token"]), **idem()}
        )
        assert r.status_code == 204, r.text


# ── minor ──────────────────────────────────────────────────────────────


async def test_soft_deleted_users_do_not_block_a_role_delete(sync_engine: Engine) -> None:
    async with q01_client() as c:
        o = await signup(c)
        org = str(o["org_id"])
        role = await create_role(c, o["access_token"], f"gone_{uuid.uuid4().hex[:6]}", [])
        email = await invite_and_accept(
            c, inviter_token=o["access_token"], role_id=role, firm_id=None
        )
        with OrmSession(sync_engine) as s:
            s.execute(text(f"SET LOCAL app.current_org_id = '{org}'"))
            s.execute(
                text("UPDATE app_user SET deleted_at = now() WHERE user_id = :u"),
                {"u": _uid(sync_engine, org, email)},
            )
            s.commit()
        r = await c.delete(f"/admin/roles/{role}", headers={**bearer(o["access_token"]), **idem()})
        assert r.status_code == 204, r.text


async def test_outrank_403_lists_codes_but_never_another_firm(sync_engine: Engine) -> None:
    """Target: org-wide reader + a bank role in firm B. Actor: org-wide user
    manager + reader, bank role only in firm A → refused in firm B."""
    async with q01_client() as c:
        o = await signup(c)
        org = str(o["org_id"])
        ot = o["access_token"]
        fa = uuid.UUID(str(o["firm_id"]))
        fb = add_sibling_firm(sync_engine, uuid.UUID(org), name="HiddenFirmB")
        mgr = await create_role(
            c, ot, f"mgr_{uuid.uuid4().hex[:5]}", ["admin.user.manage", "masters.party.read"]
        )
        bank = await create_role(c, ot, f"bk_{uuid.uuid4().hex[:5]}", ["banking.bank.read"])
        reader = await create_role(c, ot, f"rd_{uuid.uuid4().hex[:5]}", ["masters.party.read"])
        actor_e = await invite_and_accept(c, inviter_token=ot, role_id=mgr, firm_id=None)
        tgt_e = await invite_and_accept(c, inviter_token=ot, role_id=reader, firm_id=None)
    actor = _uid(sync_engine, org, actor_e)
    tgt = _uid(sync_engine, org, tgt_e)
    oid = uuid.UUID(org)
    with OrmSession(sync_engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org}'"))
        rbac_service.assign_role(s, user_id=actor, role_id=uuid.UUID(bank), firm_id=fa, org_id=oid)
        rbac_service.assign_role(s, user_id=tgt, role_id=uuid.UUID(bank), firm_id=fb, org_id=oid)
        with pytest.raises(PermissionDeniedError) as ei:
            invite_service.change_user_role(
                s,
                org_id=oid,
                actor_user_id=actor,
                target_user_id=tgt,
                new_role_id=uuid.UUID(reader),
            )
        msg = str(ei.value)
        assert "banking.bank.read" in msg
        assert str(fb) not in msg and str(fa) not in msg and "HiddenFirmB" not in msg
        # Control: actor gets the bank role in firm B too → allowed.
        rbac_service.assign_role(s, user_id=actor, role_id=uuid.UUID(bank), firm_id=fb, org_id=oid)
        invite_service.change_user_role(
            s, org_id=oid, actor_user_id=actor, target_user_id=tgt, new_role_id=uuid.UUID(reader)
        )
        s.rollback()

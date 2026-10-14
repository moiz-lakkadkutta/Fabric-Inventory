"""Q01-02: firm-level authorization — the single home for firm scoping.

Roles are granted per firm (``user_role.firm_id``; NULL = an org-wide grant).
A user may act on firm F only with a permission granted for F or org-wide.
Two layers enforce that, and both live behind this module:

1. **App layer — explicit firm targets.** ``require_permission`` (the
   dependency every business route already uses) calls
   :func:`authorize_firm` for every ``firm_id`` the request names in its path,
   query string or top-level JSON body. A firm other than the token's active
   firm must grant the route's permission (``rbac_service.get_user_permissions``
   for that firm, which includes org-wide roles) or the request is refused
   with 403. An unknown / foreign-org / deleted firm is NOT judged here — the
   route keeps its existing 404/422 so a foreign firm id leaks nothing.

2. **DB layer — everything else (by-id reads/writes, unfiltered lists,
   referenced rows).** Every business table with a ``firm_id`` carries a
   RESTRICTIVE RLS policy (migration ``210_firm_scope_rls``) that admits a
   row only when ``firm_id IS NULL`` (an org-shared master) or
   ``app_firm_in_scope(firm_id)``, i.e. the firm is in the transaction-local
   GUC ``app.current_firm_scope``:

   * ``'*'`` — every firm in the org (an org-wide grant covers everything the
     user can do, or an explicitly-marked system context such as signup).
   * ``'<uuid>,<uuid>'`` — exactly these firms.
   * unset / ``''`` / anything else — NO firm rows (fail closed).

   ``get_db_sync`` sets the GUC for every authenticated request right after
   ``app.current_org_id``, so — like org RLS — a route cannot forget it.

Scope rule (``_SCOPE_SQL``): with T = the user's permissions in the active
firm (org-wide roles + roles in that firm), the scope is ``'*'`` when the
org-wide roles alone already cover T, otherwise the firms F whose grants
(org-wide + F's roles) cover T. The active firm is in its own scope by
construction; another firm is visible only when everything the token lets
the user do is also granted there, so a by-id action authorised against the
token's permissions can never land in a firm that doesn't grant it. A user
with no grants at all gets ``''``.
"""

from __future__ import annotations

import dataclasses
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.exceptions import PermissionDeniedError
from app.models import Firm, UserRole
from app.service import rbac_service
from app.service.identity_service import TokenPayload

FIRM_SCOPE_GUC = "app.current_firm_scope"
SYSTEM_SCOPE = "*"

# One statement: computes the scope (see module docstring) for :uid in the
# active firm :fid (NULL → org-wide roles only). Mirrors
# `rbac_service.get_user_permissions` (same joins, same — deliberately
# unfiltered — role set) so the token's permissions and the RLS scope can't
# disagree. Runs under the request's org GUC, so user_role / role_permission
# are already org-filtered by RLS.
_SCOPE_SQL = """
WITH grants AS (
    SELECT ur.firm_id, p.resource || '.' || p.action AS code
      FROM user_role ur
      JOIN role_permission rp ON rp.role_id = ur.role_id
      JOIN permission p ON p.permission_id = rp.permission_id
     WHERE ur.user_id = CAST(:uid AS uuid)
),
active AS (
    SELECT code FROM grants
     WHERE firm_id IS NULL OR firm_id = CAST(:fid AS uuid)
)
SELECT CASE
    WHEN NOT EXISTS (SELECT 1 FROM active) THEN ''
    WHEN NOT EXISTS (
        SELECT code FROM active
        EXCEPT SELECT code FROM grants WHERE firm_id IS NULL
    ) THEN '*'
    ELSE coalesce((
        SELECT string_agg(f.firm_id::text, ',' ORDER BY f.firm_id::text)
          FROM (SELECT DISTINCT firm_id FROM grants WHERE firm_id IS NOT NULL) f
         WHERE NOT EXISTS (
            SELECT code FROM active
            EXCEPT SELECT code FROM grants g
                    WHERE g.firm_id IS NULL OR g.firm_id = f.firm_id
         )
    ), '')
END
"""

_SET_SCOPE_FOR_USER_SQL = text(f"SELECT set_config('{FIRM_SCOPE_GUC}', ({_SCOPE_SQL}), true)")
_SET_SCOPE_SQL = text(f"SELECT set_config('{FIRM_SCOPE_GUC}', :v, true)")
_GET_SCOPE_SQL = text(f"SELECT current_setting('{FIRM_SCOPE_GUC}', true)")


def apply_user_firm_scope(
    session: Session, *, user_id: uuid.UUID, active_firm_id: uuid.UUID | None
) -> None:
    """Compute and pin (transaction-local) the firm scope for an authenticated
    principal. Called by ``get_db_sync`` after the org GUC is set."""
    session.execute(
        _SET_SCOPE_FOR_USER_SQL,
        {"uid": str(user_id), "fid": str(active_firm_id) if active_firm_id else None},
    )


def apply_system_firm_scope(session: Session) -> None:
    """Mark the current transaction as a SYSTEM context that may touch every
    firm in the (already pinned) org. Only for paths with no end-user
    principal yet — signup bootstrap, CLI seeding. Every call site is a
    deliberate, reviewed exception to fail-closed; grep for this name."""
    session.execute(_SET_SCOPE_SQL, {"v": SYSTEM_SCOPE})


def _apply_firm_ids(session: Session, firm_ids: set[uuid.UUID]) -> None:
    session.execute(_SET_SCOPE_SQL, {"v": ",".join(sorted(str(f) for f in firm_ids))})


def current_firm_scope(session: Session) -> str | None:
    """The scope pinned on this transaction (None/'' = no firm rows)."""
    value = session.execute(_GET_SCOPE_SQL).scalar_one_or_none()
    return None if value is None else str(value)


def accessible_firm_ids(session: Session, *, user_id: uuid.UUID) -> set[uuid.UUID] | None:
    """Firms the user holds ANY grant in; ``None`` = every firm (the user has
    an org-wide role). Same rule ``/auth/switch-firm`` applies (a firm with
    zero permissions is refused), used to filter ``available_firms``."""
    rows = session.execute(select(UserRole.firm_id).where(UserRole.user_id == user_id)).all()
    firm_ids: set[uuid.UUID] = set()
    for (firm_id,) in rows:
        if firm_id is None:
            return None
        firm_ids.add(firm_id)
    return firm_ids


def authorize_firm(
    session: Session,
    *,
    current_user: TokenPayload,
    firm_id: uuid.UUID,
    permission_code: str,
) -> bool:
    """Authorise ``permission_code`` in the explicitly targeted ``firm_id``.

    Returns True when the request now acts in a firm OTHER than the token's
    active firm (the caller then re-points the DB scope with
    :func:`pin_request_firms`), False when there is nothing to do:

    * Active firm → False (``require_permission`` already checked the token's
      permissions, which ARE the active firm's).
    * Unknown / other-org / deleted firm → False; the route's own
      ``assert_firm_in_org`` / lookups produce today's 404/422, so we never
      reveal whether a firm exists in another org.
    * Same-org firm without the permission (firm-scoped or org-wide) → 403.
    """
    if current_user.firm_id is not None and firm_id == current_user.firm_id:
        return False
    firm = session.execute(
        select(Firm).where(
            Firm.firm_id == firm_id,
            Firm.org_id == current_user.org_id,
            Firm.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if firm is None:
        return False
    granted = rbac_service.get_user_permissions(
        session, user_id=current_user.user_id, firm_id=firm_id
    )
    if permission_code not in granted:
        raise PermissionDeniedError(
            f"You don't have '{permission_code}' in firm {firm.name!r}. Switch to a firm "
            "you have access to, or ask an admin to grant you a role in this firm.",
            title="No access to that firm",
        )
    return True


def principal_for_firms(
    session: Session, *, current_user: TokenPayload, firm_ids: set[uuid.UUID]
) -> TokenPayload:
    """The principal a cross-firm request runs as: the token's identity with
    ``permissions`` = the INTERSECTION of the user's permissions in every firm
    the request is pinned to (org-wide roles count in each). Handlers that
    check a permission inline therefore judge it in the firm(s) the data
    belongs to, not the token's active firm."""
    effective: set[str] | None = None
    for firm_id in firm_ids:
        granted = rbac_service.get_user_permissions(
            session, user_id=current_user.user_id, firm_id=firm_id
        )
        effective = granted if effective is None else effective & granted
    return dataclasses.replace(current_user, permissions=tuple(sorted(effective or set())))


def pin_request_firms(session: Session, firm_ids: set[uuid.UUID]) -> None:
    """The request explicitly acts in ``firm_ids`` (each authorised by
    :func:`authorize_firm`): re-point the transaction's DB scope to exactly
    those firms so the DB admits what the app layer authorised and nothing
    beyond it. A ``'*'`` scope already admits them and is left alone."""
    if firm_ids and current_firm_scope(session) != SYSTEM_SCOPE:
        _apply_firm_ids(session, firm_ids)


__all__ = [
    "FIRM_SCOPE_GUC",
    "SYSTEM_SCOPE",
    "accessible_firm_ids",
    "apply_system_firm_scope",
    "apply_user_firm_scope",
    "authorize_firm",
    "current_firm_scope",
    "pin_request_firms",
    "principal_for_firms",
]

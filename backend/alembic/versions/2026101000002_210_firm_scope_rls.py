"""Q01-02: firm-level RLS — a RESTRICTIVE firm-scope policy on every business
table that carries ``firm_id``.

Org RLS (the existing PERMISSIVE ``<table>_rls`` policies) keeps tenants
apart; nothing kept FIRMS apart inside one org. Roles are granted per firm
(``user_role.firm_id``), yet ~90 by-id routes only had org RLS, so a user
granted in firm F1 could read/act on F2's rows by id. This migration adds the
DB-layer half of the fix (the app-layer half is ``require_permission`` →
``firm_scope_service.authorize_firm`` for explicit ``firm_id`` targets).

What it creates
---------------
* ``app_firm_in_scope(uuid) → boolean`` — a plain (NOT security definer),
  STABLE, inlinable SQL function reading the transaction-local GUC
  ``app.current_firm_scope``:
    - ``'*'``                → every firm (org-wide principal / system context)
    - ``'<uuid>,<uuid>,…'``  → exactly those firms
    - unset, ``''`` or anything else → false  (FAIL CLOSED)
  ``current_setting(..., true)`` (missing_ok) is used so an unset GUC denies
  instead of raising (the Q01-07 lesson). Ids are compared as TEXT, so a
  malformed scope can never raise a cast error — it just matches nothing.
* ``<table>_firm_scope`` on each table below:
    ``AS RESTRICTIVE FOR ALL
      USING (firm_id IS NULL OR app_firm_in_scope(firm_id))
      WITH CHECK (firm_id IS NULL OR app_firm_in_scope(firm_id))``
  RESTRICTIVE policies are AND-ed with the existing permissive org policy, so
  org isolation is untouched and this can only ever REMOVE rows.
  ``firm_id IS NULL`` rows are org-shared masters (party / item / sku /
  ledger / price_list / scheduled_report allow NULL) and stay visible
  org-wide, exactly as their semantics say.

Who sets the GUC
----------------
``get_db_sync`` sets it for every request carrying an access token, right
after ``app.current_org_id`` (``firm_scope_service.apply_user_firm_scope``).
Paths with no principal leave it unset → zero firm rows. The only opt-in to
``'*'`` is ``firm_scope_service.apply_system_firm_scope`` (signup bootstrap,
seed CLI). The migration role (superuser / BYPASSRLS) is unaffected.

Deliberately NOT covered (identity / config / log tables, judged per row):
* ``firm`` — the tenancy node itself; switch-firm, login and /auth/me must
  resolve sibling firms (firm names are not business data).
* ``user_role``, ``user_firm_scope``, ``user_invite`` — identity; read while
  computing the scope itself and by signup / invite-accept with no principal.
* ``audit_log`` — append-only, written by unauthenticated auth paths
  (login/refresh/logout carry a firm_id) and INSERT…RETURNING would need the
  SELECT policy to pass; the only audit route (`/v1/audit/verify`) is an org-wide hash-chain check.
* ``feature_flag`` — per-firm config read by login / refresh / me paths; its
  existing policy is already a firm→org subquery.
Child/line tables without ``firm_id`` are reached only through their parent
(which IS covered), so a hidden parent hides its lines from every route.

Backward-compatible for the app (the GUC is set by the same release); a
rollback of the app without this downgrade would fail closed on firm tables,
so downgrade the schema first. Downgrade drops the policies and function.

Revision ID: 210_firm_scope_rls
Revises: 209_dc_invoice_link
Create Date: 2026-10-10
"""

from __future__ import annotations

from alembic import op

revision: str = "210_firm_scope_rls"
down_revision: str = "209_dc_invoice_link"
branch_labels = None
depends_on = None

# Every public table with a `firm_id` column at 209_dc_invoice_link, minus the
# exclusions documented above. `test_q01_firm_rls.py` fails if a new table
# with `firm_id` ships without this policy (or an explicit exemption).
FIRM_SCOPED_TABLES: tuple[str, ...] = (
    "bank_account",
    "bom",
    "budget",
    "cheque",
    "commission_scheme",
    "consignment_shipment",
    "cost_centre",
    "customer_credit_profile",
    "delivery_challan",
    "design",
    "document_series",
    "electronic_cash_ledger",
    "electronic_credit_ledger",
    "eway_bill",
    "expense_category",
    "fixed_asset",
    "grn",
    "gstr_filing",
    "invoice_share",
    "irn",
    "itc04_entry",
    "item",
    "job_work_order",
    "job_work_order_line",
    "job_work_receipt",
    "job_work_receipt_line",
    "labour_slip",
    "landed_cost_entry",
    "ledger",
    "loan",
    "location",
    "lot",
    "manufacturing_order",
    "material_issue",
    "mo_operation",
    "operation_master",
    "overhead_rate",
    "party",
    "payment_allocation",
    "pick_wave",
    "price_list",
    "production_event",
    "purchase_invoice",
    "purchase_order",
    "purchase_return",
    "qc_plan",
    "quotation",
    "routing",
    "sales_invoice",
    "sales_order",
    "sales_return",
    "scheduled_report",
    "sku",
    "stock_adjustment",
    "stock_ledger",
    "stock_position",
    "stock_take",
    "tds_entry",
    "user_migration",
    "voucher",
)

_PREDICATE = "firm_id IS NULL OR app_firm_in_scope(firm_id)"


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION app_firm_in_scope(p_firm_id uuid) RETURNS boolean
        LANGUAGE sql STABLE PARALLEL SAFE
        AS $$
            SELECT CASE coalesce(current_setting('app.current_firm_scope', true), '')
                WHEN '' THEN false
                WHEN '*' THEN true
                ELSE p_firm_id::text = ANY (
                    string_to_array(current_setting('app.current_firm_scope', true), ',')
                )
            END
        $$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION app_firm_in_scope(uuid) IS "
        "'Q01-02 firm RLS: true iff the firm is in app.current_firm_scope "
        "(''*'' = all firms; unset/empty = none, fail closed)'"
    )
    for table in FIRM_SCOPED_TABLES:
        op.execute(
            f"CREATE POLICY {table}_firm_scope ON {table} AS RESTRICTIVE FOR ALL "
            f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
        )


def downgrade() -> None:
    for table in FIRM_SCOPED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_firm_scope ON {table}")
    op.execute("DROP FUNCTION IF EXISTS app_firm_in_scope(uuid)")

"""TASK-INT-12: dashboard KPI rewrite (P1-8).

QA on 2026-05-06 found two of the six KPIs are mock-only in live mode
(`low_stock_skus` returns 0 because inventory wiring isn't live;
`supplier_ap` returns 0 because purchase invoices aren't live yet) and
one ASKED-FOR KPI was missing entirely (GST-collected MTD — textile
businesses watch this for liability planning).

Per /grill-me Q8: drop the two mock-only cards, add `gst_collected_mtd`.
The dashboard becomes 5 actually-meaningful cards instead of 6 with
two zeros.
"""

from __future__ import annotations

from app.service import dashboard_service


def test_kpi_keys_match_int12_contract() -> None:
    """`KpiKey` literal must contain exactly the post-INT-12 set:
    outstanding_ar, overdue_ar, sales_today, sales_mtd, gst_collected_mtd.

    Asserting on the type alias rather than a runtime build keeps the
    test fast (no DB) and forces any future drift to update both the
    type and this test in lock-step.
    """
    import typing

    keys = set(typing.get_args(dashboard_service.KpiKey))
    assert keys == {
        "outstanding_ar",
        "overdue_ar",
        "sales_today",
        "sales_mtd",
        "gst_collected_mtd",
    }, f"unexpected KPI key set: {keys}"


def test_kpi_keys_no_longer_include_mock_only_cards() -> None:
    """Regression guard: `low_stock_skus` and `supplier_ap` must be
    removed from the dashboard. They were always 0 in live mode (no
    inventory wiring, no purchase wiring yet), training users to
    ignore the dashboard."""
    import typing

    keys = set(typing.get_args(dashboard_service.KpiKey))
    assert "low_stock_skus" not in keys, (
        "low_stock_skus is mock-only — drop until inventory module ships"
    )
    assert "supplier_ap" not in keys, "supplier_ap is mock-only — drop until purchase module ships"

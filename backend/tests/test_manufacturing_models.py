"""TASK-TR-A01: schema-parity tests for the Manufacturing ORM models.

The 11 Manufacturing tables already exist in the migrated database
(``schema/ddl.sql``). This test asserts the SQLAlchemy models in
``app/models/manufacturing.py`` (plus the pre-existing ``CostCentre``)
faithfully mirror that schema:

  1. ``Base.metadata`` registers all 11 tables and the models import
     cleanly — a pure-import check, runs without a database.
  2. For each modelled table, the ORM column set / nullability / type
     family / primary key line up with the *live* migrated schema,
     reflected via SQLAlchemy's inspector.

The repo-wide ``test_orm_ddl_drift.py`` is the stronger, exhaustive gate
(it diffs FKs, server-defaults, unique constraints via alembic
autogenerate). This file is the Manufacturing-scoped, human-readable
companion: when it fails, the message points straight at the offending
table + column.

DB-bound assertions skip cleanly without Postgres (local dev) and
fail loud in CI — same contract as ``conftest.py``'s ``sync_engine``.
"""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.models import Base

# The 11 Manufacturing tables. ``cost_centre`` is modelled in masters.py
# as ``CostCentre`` (pre-existing); the other 10 land in manufacturing.py.
MANUFACTURING_TABLES = (
    "design",
    "operation_master",
    "cost_centre",
    "bom",
    "bom_line",
    "routing",
    "routing_edge",
    "manufacturing_order",
    "mo_material_line",
    "mo_operation",
    "production_event",
)


# ──────────────────────────────────────────────────────────────────────
# 1. Import + registration — no database required
# ──────────────────────────────────────────────────────────────────────


def test_manufacturing_models_import_cleanly() -> None:
    """The model classes + enums import without error and are re-exported
    from ``app.models``."""
    from app.models import (
        Bom,
        BomLine,
        CostCentre,
        Design,
        ManufacturingOrder,
        MoMaterialLine,
        MoOperation,
        MoOperationState,
        MoStatus,
        MoType,
        OperationMaster,
        OperationType,
        ProductionEvent,
        Routing,
        RoutingEdge,
        RoutingEdgeType,
    )

    # __tablename__ wiring is correct.
    assert Design.__tablename__ == "design"
    assert Bom.__tablename__ == "bom"
    assert BomLine.__tablename__ == "bom_line"
    assert OperationMaster.__tablename__ == "operation_master"
    assert Routing.__tablename__ == "routing"
    assert RoutingEdge.__tablename__ == "routing_edge"
    assert CostCentre.__tablename__ == "cost_centre"
    assert ManufacturingOrder.__tablename__ == "manufacturing_order"
    assert MoMaterialLine.__tablename__ == "mo_material_line"
    assert MoOperation.__tablename__ == "mo_operation"
    assert ProductionEvent.__tablename__ == "production_event"

    # Enum values mirror the Postgres CREATE TYPE definitions.
    assert {e.value for e in MoStatus} == {
        "DRAFT",
        "RELEASED",
        "IN_PROGRESS",
        "COMPLETED",
        "CLOSED",
    }
    assert {e.value for e in MoType} == {
        "SAMPLE",
        "PRE_PRODUCTION",
        "BULK",
        "REWORK",
    }
    assert {e.value for e in RoutingEdgeType} == {
        "FINISH_TO_START",
        "START_TO_START",
        "PARTIAL_FINISH_TO_START",
    }
    assert {e.value for e in MoOperationState} == {
        "PENDING",
        "READY",
        "DISPATCHED",
        "ACKNOWLEDGED",
        "IN_PROGRESS",
        "RECEIVED_PARTIAL",
        "RECEIVED_FULL",
        "QC_PENDING",
        "REWORK",
        "CLOSED",
        "SKIPPED",
        "CANCELLED",
    }
    assert {e.value for e in OperationType} == {
        "WEAVING",
        "DYEING",
        "EMBROIDERY",
        "STITCHING",
        "QC",
        "PACKING",
        "OTHER",
    }


def test_base_metadata_registers_all_manufacturing_tables() -> None:
    """All 11 Manufacturing tables are registered in ``Base.metadata`` so
    alembic autogenerate / the drift gate can see them."""
    registered = set(Base.metadata.tables.keys())
    missing = [t for t in MANUFACTURING_TABLES if t not in registered]
    assert not missing, f"Manufacturing tables missing from Base.metadata: {missing}"


# ──────────────────────────────────────────────────────────────────────
# 2. Column-level parity against the live migrated schema
# ──────────────────────────────────────────────────────────────────────


def _type_family(type_repr: str) -> str:
    """Collapse a column-type repr to a coarse family for cross-checking
    ORM ``Mapped[...]`` types against reflected DB types. Precision /
    length differences are deliberately ignored here — the exhaustive
    ``test_orm_ddl_drift.py`` gate handles exact type comparison."""
    t = type_repr.upper()
    if "UUID" in t:
        return "uuid"
    if "NUMERIC" in t or "DECIMAL" in t:
        return "numeric"
    if "INTEGER" in t or "SMALLINT" in t or "BIGINT" in t:
        return "integer"
    if "BOOLEAN" in t:
        return "boolean"
    if "TIMESTAMP" in t or "DATETIME" in t:
        return "timestamp"
    if "DATE" in t:
        return "date"
    if "JSON" in t:
        return "json"
    if "BYTEA" in t or "LARGEBINARY" in t or "BLOB" in t:
        return "binary"
    if "VARCHAR" in t or "CHAR" in t or "STRING" in t or "TEXT" in t or "ENUM" in t:
        # Postgres enum columns reflect as their type name (e.g. MO_STATUS);
        # the ORM declares them via PG ENUM. Both collapse to "string-ish".
        return "string"
    # Native enum types reflect under their own name — treat as string-ish.
    return "string"


def test_manufacturing_models_match_live_schema(sync_engine: Engine) -> None:
    """For each modelled Manufacturing table, the ORM's columns line up
    with the live migrated DB: same column names, same nullability, same
    coarse type family, same primary key."""
    inspector = inspect(sync_engine)
    db_tables = set(inspector.get_table_names())

    failures: list[str] = []

    for table_name in MANUFACTURING_TABLES:
        if table_name not in db_tables:
            failures.append(f"{table_name}: table missing from live DB")
            continue
        if table_name not in Base.metadata.tables:
            failures.append(f"{table_name}: table not registered in Base.metadata")
            continue

        orm_table = Base.metadata.tables[table_name]
        db_columns = {c["name"]: c for c in inspector.get_columns(table_name)}
        orm_columns = {c.name: c for c in orm_table.columns}

        # Column set parity.
        only_orm = sorted(set(orm_columns) - set(db_columns))
        only_db = sorted(set(db_columns) - set(orm_columns))
        if only_orm:
            failures.append(f"{table_name}: ORM has columns not in DB: {only_orm}")
        if only_db:
            failures.append(f"{table_name}: DB has columns not in ORM: {only_db}")

        # Per-column nullability + type family.
        for col_name in sorted(set(orm_columns) & set(db_columns)):
            orm_col = orm_columns[col_name]
            db_col = db_columns[col_name]

            if orm_col.nullable != db_col["nullable"]:
                failures.append(
                    f"{table_name}.{col_name}: nullable mismatch — "
                    f"ORM={orm_col.nullable} DB={db_col['nullable']}"
                )

            orm_family = _type_family(repr(orm_col.type))
            db_family = _type_family(repr(db_col["type"]))
            if orm_family != db_family:
                failures.append(
                    f"{table_name}.{col_name}: type family mismatch — "
                    f"ORM={orm_family} ({orm_col.type!r}) "
                    f"DB={db_family} ({db_col['type']!r})"
                )

        # Primary key parity.
        db_pk = set(inspector.get_pk_constraint(table_name)["constrained_columns"])
        orm_pk = {c.name for c in orm_table.primary_key.columns}
        if db_pk != orm_pk:
            failures.append(
                f"{table_name}: primary key mismatch — ORM={sorted(orm_pk)} DB={sorted(db_pk)}"
            )

    assert not failures, "Manufacturing ORM <-> live-schema parity failures:\n  - " + (
        "\n  - ".join(failures)
    )


def test_money_and_qty_columns_are_numeric_never_float() -> None:
    """Money / quantity columns must be NUMERIC — never float. Spot-check
    the load-bearing ones across the Manufacturing models."""
    numeric_columns = {
        "bom_line": ["qty_required"],
        "routing_edge": ["threshold_qty", "threshold_pct"],
        "manufacturing_order": [
            "planned_qty",
            "produced_qty",
            "scrap_qty",
            "by_product_qty",
            "cost_pool",
        ],
        "mo_material_line": ["qty_required", "qty_issued", "qty_scrap"],
        "mo_operation": [
            "qty_in",
            "qty_out",
            "qty_rejected",
            "qty_wastage",
            "qty_byproduct",
            "cost_accrued",
        ],
        "operation_master": ["default_duration_mins"],
    }
    for table_name, columns in numeric_columns.items():
        orm_table = Base.metadata.tables[table_name]
        for col_name in columns:
            col = orm_table.columns[col_name]
            assert _type_family(repr(col.type)) == "numeric", (
                f"{table_name}.{col_name} must be NUMERIC, got {col.type!r}"
            )
            # Python side: NUMERIC binds to Decimal, not float.
            assert col.type.python_type is decimal.Decimal


def test_mo_operation_carries_forward_alter_columns() -> None:
    """`mo_operation` gets a forward ALTER TABLE (state machine + karigar
    + event hooks). Assert those columns made it onto the model."""
    cols = set(Base.metadata.tables["mo_operation"].columns.keys())
    forward_alter_columns = {
        "firm_id",
        "state",
        "karigar_party_id",
        "executor",
        "outward_challan_id",
        "inward_challan_id",
        "qty_rejected",
        "qty_wastage",
        "qty_byproduct",
        "cost_accrued",
        "rework_of_mo_operation_id",
        "is_rework_paid",
        "expected_return_date",
        "acknowledged_at",
        "version",
    }
    missing = forward_alter_columns - cols
    assert not missing, f"mo_operation missing forward-ALTER columns: {sorted(missing)}"
    # Legacy free-text `status` is kept in parallel with the typed `state`.
    assert "status" in cols and "state" in cols


def test_timestamp_columns_are_timezone_aware() -> None:
    """All timestamp columns store TIMESTAMPTZ (timezone-aware) per the
    repo convention — never naive."""
    bad: list[str] = []
    for table_name in MANUFACTURING_TABLES:
        for col in Base.metadata.tables[table_name].columns:
            is_datetime = col.type.python_type is datetime.datetime
            if is_datetime and not getattr(col.type, "timezone", False):
                bad.append(f"{table_name}.{col.name}")
    assert not bad, f"timestamp columns must be timezone-aware (TIMESTAMPTZ): {bad}"

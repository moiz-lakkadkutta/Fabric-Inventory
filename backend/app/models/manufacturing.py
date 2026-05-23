"""Manufacturing-domain ORM models (TASK-TR-A01).

Ten tables mirroring the base ``schema/ddl.sql`` (loaded by the baseline
Alembic migration). The eleventh Manufacturing table — ``cost_centre`` —
is already modelled in ``masters.py`` as ``CostCentre``; we reference it
by FK string here but do not redefine it.

Tables modelled here:

  - ``Design``              — a designed product (suit / fabric pattern).
  - ``Bom`` / ``BomLine``   — bill of materials, versioned per finished item.
  - ``OperationMaster``     — a reusable shop-floor operation definition.
  - ``Routing`` / ``RoutingEdge`` — operation DAG for a design, versioned.
  - ``ManufacturingOrder``  — MO header; the unit of production work.
  - ``MoMaterialLine``      — planned/issued raw-material lines on an MO.
  - ``MoOperation``         — per-MO operation instances + state machine.
  - ``ProductionEvent``     — append-only, idempotent event log for MOs.

State machines (driven by the future ``manufacturing_service``, never
written directly from routers):

  - ``ManufacturingOrder.status`` — ``mo_status`` enum:
        DRAFT → RELEASED → IN_PROGRESS → COMPLETED → CLOSED
  - ``MoOperation.state`` — ``mo_operation_state`` enum: the richer
        per-operation lifecycle (PENDING … CLOSED / SKIPPED / CANCELLED).

DDL notes folded in here:

  - **Audit-columns sweep.** The DDL's ``$audit_sweep$`` DO block adds
    ``updated_at`` / ``created_by`` / ``updated_by`` / ``deleted_at`` to
    *every* tenant-scoped table that doesn't already have them, except an
    explicit exempt list. ``production_event`` is exempt (append-only);
    all other Manufacturing tables get the full audit set even though
    their base ``CREATE TABLE`` only declares ``created_at``. So every
    model here except ``ProductionEvent`` carries TimestampMixin +
    SoftDeleteMixin, and the audit ``created_by`` / ``updated_by``.
  - ``design`` / ``bom`` / ``routing`` / ``manufacturing_order`` declare
    ``created_by`` *inline with an FK to app_user* in the base DDL — the
    sweep then skips it (column already exists). The other tables get a
    sweep-added ``created_by`` that is a *plain UUID with no FK*. Models
    mirror that split: inline-FK tables declare ``created_by`` by hand;
    the rest inherit ``AuditByMixin`` (plain UUID, no FK).
  - ``mo_operation`` carries a forward ``ALTER TABLE`` (the "state machine
    + karigar + event-sourcing hooks" block) that adds ``firm_id``,
    ``state``, ``karigar_party_id``, qty/cost columns, optimistic-lock
    ``version``, etc. ``mo_operation.status`` (the original free-text
    VARCHAR) is kept in parallel with the typed ``state`` column — the
    DDL did not drop it.
  - ``mo_operation.outward_challan_id`` / ``inward_challan_id`` are plain
    UUID columns with **no FK enforcement anywhere** — neither at the ORM
    level nor at the DB level. The original ``outward_challan`` /
    ``inward_challan`` tables were dropped (CASCADE) by TASK-CUT-305's
    jobwork rework, taking the DB-level FK with them. A future task will
    model the new jobwork target tables and re-add the FK (both ORM and
    DB); until then these columns are unenforced UUIDs.
  - ``operation_type`` is a Postgres enum not modelled elsewhere — defined
    here as ``OperationType`` since ``operation_master`` needs it.
"""

from __future__ import annotations

import datetime
import enum
import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .masters import _UOM_TYPE_PG, UomType
from .mixins import AuditByMixin, SoftDeleteMixin, TimestampMixin

_UUID_DEFAULT = func.gen_random_uuid()


# ──────────────────────────────────────────────────────────────────────
# Enums (bound to existing Postgres types — create_type=False)
# ──────────────────────────────────────────────────────────────────────


class MoStatus(enum.StrEnum):
    """MO header lifecycle — `mo_status` Postgres enum."""

    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"


class MoType(enum.StrEnum):
    """MO category — `mo_type` Postgres enum."""

    SAMPLE = "SAMPLE"
    PRE_PRODUCTION = "PRE_PRODUCTION"
    BULK = "BULK"
    REWORK = "REWORK"


class RoutingEdgeType(enum.StrEnum):
    """Routing-DAG edge dependency — `routing_edge_type` Postgres enum."""

    FINISH_TO_START = "FINISH_TO_START"
    START_TO_START = "START_TO_START"
    PARTIAL_FINISH_TO_START = "PARTIAL_FINISH_TO_START"


class MoOperationState(enum.StrEnum):
    """Per-operation lifecycle — `mo_operation_state` Postgres enum.

    Added by the forward `ALTER TABLE mo_operation` block; richer than the
    legacy free-text `status` column, which is kept in parallel.
    """

    PENDING = "PENDING"
    READY = "READY"
    DISPATCHED = "DISPATCHED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_PROGRESS = "IN_PROGRESS"
    RECEIVED_PARTIAL = "RECEIVED_PARTIAL"
    RECEIVED_FULL = "RECEIVED_FULL"
    QC_PENDING = "QC_PENDING"
    REWORK = "REWORK"
    CLOSED = "CLOSED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class OperationType(enum.StrEnum):
    """Shop-floor operation category — `operation_type` Postgres enum.

    Not modelled elsewhere; defined here because `operation_master`
    references it.
    """

    WEAVING = "WEAVING"
    DYEING = "DYEING"
    EMBROIDERY = "EMBROIDERY"
    STITCHING = "STITCHING"
    QC = "QC"
    PACKING = "PACKING"
    OTHER = "OTHER"


_MO_STATUS_PG = PG_ENUM(MoStatus, name="mo_status", create_type=False, native_enum=True)
_MO_TYPE_PG = PG_ENUM(MoType, name="mo_type", create_type=False, native_enum=True)
_ROUTING_EDGE_TYPE_PG = PG_ENUM(
    RoutingEdgeType, name="routing_edge_type", create_type=False, native_enum=True
)
_MO_OPERATION_STATE_PG = PG_ENUM(
    MoOperationState, name="mo_operation_state", create_type=False, native_enum=True
)
_OPERATION_TYPE_PG = PG_ENUM(
    OperationType, name="operation_type", create_type=False, native_enum=True
)


# ──────────────────────────────────────────────────────────────────────
# Design — a designed product (suit / fabric pattern)
# ──────────────────────────────────────────────────────────────────────


class Design(Base, TimestampMixin, SoftDeleteMixin):
    """A designed product. BOMs and routings hang off a design.

    Base DDL ships `created_at` / `updated_at` and an inline `created_by`
    FK; the audit sweep adds `updated_by` (plain UUID) and `deleted_at`.
    `created_by` keeps its inline FK to app_user, so it's declared by hand
    rather than via AuditByMixin.
    """

    __tablename__ = "design"
    __table_args__ = (UniqueConstraint("firm_id", "code", name="design_firm_id_code_key"),)

    design_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_centre_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("cost_centre.cost_centre_id", ondelete="SET NULL"),
        nullable=True,
    )
    # Inline FK in base DDL (sweep skips it — column already exists).
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    # Audit-sweep adds this (plain UUID, no FK).
    updated_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)


# ──────────────────────────────────────────────────────────────────────
# BOM + BOM lines
# ──────────────────────────────────────────────────────────────────────


class Bom(Base, TimestampMixin, SoftDeleteMixin):
    """Bill of materials — versioned per `(firm, finished_item, version)`.

    Inline `created_by` FK in base DDL; `updated_by` / `deleted_at` from
    the audit sweep.
    """

    __tablename__ = "bom"
    __table_args__ = (
        UniqueConstraint(
            "firm_id",
            "finished_item_id",
            "version_number",
            name="bom_firm_id_finished_item_id_version_number_key",
        ),
    )

    bom_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=False,
    )
    design_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("design.design_id", ondelete="RESTRICT"),
        nullable=False,
    )
    finished_item_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("item.item_id", ondelete="RESTRICT"),
        nullable=False,
    )
    version_number: Mapped[int | None] = mapped_column(
        SmallInteger, server_default=text("1"), nullable=True
    )
    is_active: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("true"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    lines: Mapped[list[BomLine]] = relationship(back_populates="bom", cascade="all, delete-orphan")


class BomLine(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    """One component line on a BOM. Base DDL ships only `created_at`; the
    audit sweep adds `updated_at` / `created_by` / `updated_by` /
    `deleted_at` (all plain UUID — AuditByMixin)."""

    __tablename__ = "bom_line"

    bom_line_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    bom_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("bom.bom_id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("item.item_id", ondelete="RESTRICT"),
        nullable=False,
    )
    qty_required: Mapped[Any] = mapped_column(Numeric(15, 4), nullable=False)
    # `uom` is the shared `uom_type` Postgres enum (modelled in masters.py
    # as UomType). Reuse the module-level `_UOM_TYPE_PG` binding so we don't
    # re-create the type and we get proper Python type narrowing.
    uom: Mapped[UomType] = mapped_column(_UOM_TYPE_PG, nullable=False)
    is_optional: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )
    part_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sequence: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    bom: Mapped[Bom] = relationship(back_populates="lines")


# ──────────────────────────────────────────────────────────────────────
# Operation master
# ──────────────────────────────────────────────────────────────────────


class OperationMaster(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    """A reusable shop-floor operation definition. Base DDL ships only
    `created_at`; audit sweep adds the rest (plain-UUID audit columns)."""

    __tablename__ = "operation_master"
    __table_args__ = (
        UniqueConstraint("firm_id", "code", name="operation_master_firm_id_code_key"),
    )

    operation_master_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    operation_type: Mapped[OperationType | None] = mapped_column(_OPERATION_TYPE_PG, nullable=True)
    default_duration_mins: Mapped[Any | None] = mapped_column(Numeric(10, 2), nullable=True)
    cost_centre_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("cost_centre.cost_centre_id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("true"), nullable=True
    )


# ──────────────────────────────────────────────────────────────────────
# Routing + routing edges (the operation DAG)
# ──────────────────────────────────────────────────────────────────────


class Routing(Base, TimestampMixin, SoftDeleteMixin):
    """An operation routing for a design — versioned per `(firm, code, version)`.

    Inline `created_by` FK in base DDL; `updated_by` / `deleted_at` from
    the audit sweep.
    """

    __tablename__ = "routing"
    __table_args__ = (
        UniqueConstraint(
            "firm_id",
            "code",
            "version_number",
            name="routing_firm_id_code_version_number_key",
        ),
    )

    routing_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=False,
    )
    design_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("design.design_id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    version_number: Mapped[int | None] = mapped_column(
        SmallInteger, server_default=text("1"), nullable=True
    )
    is_active: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("true"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    # A05 review (M3): the topological sort over these edges has multiple
    # valid orders on diamond DAGs (A→B, A→C, B→D, C→D). Pinning the
    # relationship loader to ORDER BY ``from_operation_id, to_operation_id``
    # gives the downstream Kahn sort a stable starting point so two MOs
    # created from the same routing land identical ``operation_sequence``
    # values. The Kahn frontier ALSO sorts ties by ``operation_master_id``
    # UUID — see ``mo_service._topological_order_operations``. Defense
    # in depth: the relationship's ORDER BY alone isn't enough because
    # the topo sort's frontier order matters more than the input order.
    edges: Mapped[list[RoutingEdge]] = relationship(
        back_populates="routing",
        cascade="all, delete-orphan",
        order_by="RoutingEdge.from_operation_id, RoutingEdge.to_operation_id",
    )


class RoutingEdge(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    """One directed edge in a routing DAG: `from_operation → to_operation`.
    Base DDL ships only `created_at`; audit sweep adds the rest."""

    __tablename__ = "routing_edge"

    routing_edge_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    routing_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("routing.routing_id", ondelete="CASCADE"),
        nullable=False,
    )
    from_operation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("operation_master.operation_master_id", ondelete="RESTRICT"),
        nullable=False,
    )
    to_operation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("operation_master.operation_master_id", ondelete="RESTRICT"),
        nullable=False,
    )
    edge_type: Mapped[RoutingEdgeType | None] = mapped_column(
        _ROUTING_EDGE_TYPE_PG,
        server_default=text("'FINISH_TO_START'::routing_edge_type"),
        nullable=True,
    )
    threshold_qty: Mapped[Any | None] = mapped_column(Numeric(15, 4), nullable=True)
    threshold_pct: Mapped[Any | None] = mapped_column(Numeric(5, 2), nullable=True)
    sequence: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    routing: Mapped[Routing] = relationship(back_populates="edges")


# ──────────────────────────────────────────────────────────────────────
# Manufacturing order + material lines + operation instances
# ──────────────────────────────────────────────────────────────────────


class ManufacturingOrder(Base, TimestampMixin, SoftDeleteMixin):
    """MO header — the unit of production work. State machine in
    `manufacturing_service`; never write `status` directly from routers.

    Base DDL ships `created_at` / `updated_at` / `deleted_at`, an inline
    `created_by` FK, and a `closed_at` timestamp; the audit sweep adds
    `updated_by` (plain UUID).
    """

    __tablename__ = "manufacturing_order"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "firm_id",
            "series",
            "number",
            name="manufacturing_order_org_id_firm_id_series_number_key",
        ),
    )

    manufacturing_order_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=False,
    )
    series: Mapped[str] = mapped_column(String(50), nullable=False)
    number: Mapped[str] = mapped_column(String(50), nullable=False)
    design_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("design.design_id", ondelete="RESTRICT"),
        nullable=False,
    )
    finished_item_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("item.item_id", ondelete="RESTRICT"),
        nullable=False,
    )
    bom_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("bom.bom_id", ondelete="SET NULL"),
        nullable=True,
    )
    routing_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("routing.routing_id", ondelete="SET NULL"),
        nullable=True,
    )
    mo_type: Mapped[MoType | None] = mapped_column(
        _MO_TYPE_PG, server_default=text("'BULK'::mo_type"), nullable=True
    )
    status: Mapped[MoStatus | None] = mapped_column(
        _MO_STATUS_PG, server_default=text("'DRAFT'::mo_status"), nullable=True
    )
    mo_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    planned_qty: Mapped[Any] = mapped_column(Numeric(15, 4), nullable=False)
    produced_qty: Mapped[Any | None] = mapped_column(
        Numeric(15, 4), server_default=text("0"), nullable=True
    )
    scrap_qty: Mapped[Any | None] = mapped_column(
        Numeric(15, 4), server_default=text("0"), nullable=True
    )
    by_product_qty: Mapped[Any | None] = mapped_column(
        Numeric(15, 4), server_default=text("0"), nullable=True
    )
    completion_policy: Mapped[str | None] = mapped_column(
        String(50), server_default=text("'ALL_OR_NONE'"), nullable=True
    )
    cost_pool: Mapped[Any | None] = mapped_column(
        Numeric(15, 2), server_default=text("0"), nullable=True
    )
    cost_centre_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("cost_centre.cost_centre_id", ondelete="SET NULL"),
        nullable=True,
    )
    # A05 followups (M2): planned start / end DATEs, both nullable. Pre-
    # existing MOs (created before the followup migration) have NULL for
    # both; new MOs MAY populate either or both, and the service-layer
    # ``create_mo`` validates ``end >= start`` when both are present.
    planned_start_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    planned_end_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    closed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Audit-sweep adds this (plain UUID, no FK).
    updated_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    material_lines: Mapped[list[MoMaterialLine]] = relationship(
        back_populates="manufacturing_order", cascade="all, delete-orphan"
    )
    operations: Mapped[list[MoOperation]] = relationship(
        back_populates="manufacturing_order", cascade="all, delete-orphan"
    )


class MoMaterialLine(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    """A planned/issued raw-material line on an MO. Base DDL ships only
    `created_at`; audit sweep adds the rest."""

    __tablename__ = "mo_material_line"

    mo_material_line_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    manufacturing_order_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("manufacturing_order.manufacturing_order_id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("item.item_id", ondelete="RESTRICT"),
        nullable=False,
    )
    qty_required: Mapped[Any | None] = mapped_column(Numeric(15, 4), nullable=True)
    qty_issued: Mapped[Any | None] = mapped_column(
        Numeric(15, 4), server_default=text("0"), nullable=True
    )
    qty_scrap: Mapped[Any | None] = mapped_column(
        Numeric(15, 4), server_default=text("0"), nullable=True
    )
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("lot.lot_id", ondelete="SET NULL"),
        nullable=True,
    )
    # A05 followups (M1): propagated from ``bom_line.is_optional`` at MO
    # materialization time. Before this column existed, ``create_mo``
    # SKIPPED optional BOM lines entirely; now we persist the flag so
    # A06 (material issue) and the UI can branch on it without
    # re-walking the BOM.
    is_optional: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    manufacturing_order: Mapped[ManufacturingOrder] = relationship(back_populates="material_lines")


class MoOperation(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    """A per-MO operation instance + its state machine.

    Base DDL ships `created_at` / `updated_at` plus a free-text `status`
    column. The forward "state machine + karigar + event-sourcing hooks"
    `ALTER TABLE` adds the typed `state` column (kept in parallel with
    `status`), `firm_id`, karigar/executor fields, the outward/inward
    challan links, qty/cost columns, the rework self-FK, and the
    optimistic-locking `version` counter. The audit sweep then adds
    `created_by` / `updated_by` / `deleted_at` (plain-UUID — AuditByMixin).

    `outward_challan_id` / `inward_challan_id` are plain UUID columns
    with **no FK enforcement anywhere**: TASK-CUT-305's jobwork rework
    dropped the original `outward_challan` / `inward_challan` tables
    (CASCADE), removing the DB-level FK along with them. A future task
    will model the new jobwork target tables and re-add the FK.
    """

    __tablename__ = "mo_operation"

    mo_operation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    manufacturing_order_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("manufacturing_order.manufacturing_order_id", ondelete="CASCADE"),
        nullable=False,
    )
    operation_master_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("operation_master.operation_master_id", ondelete="RESTRICT"),
        nullable=False,
    )
    operation_sequence: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    qty_in: Mapped[Any | None] = mapped_column(Numeric(15, 4), nullable=True)
    qty_out: Mapped[Any | None] = mapped_column(
        Numeric(15, 4), server_default=text("0"), nullable=True
    )
    start_date: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_date: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Legacy free-text status (kept in parallel with the typed `state`).
    status: Mapped[str | None] = mapped_column(
        String(50), server_default=text("'PENDING'"), nullable=True
    )

    # --- forward ALTER TABLE: state machine + karigar + event hooks ---
    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=False,
    )
    state: Mapped[MoOperationState] = mapped_column(
        _MO_OPERATION_STATE_PG,
        server_default=text("'PENDING'::mo_operation_state"),
        nullable=False,
    )
    karigar_party_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("party.party_id", ondelete="RESTRICT"),
        nullable=True,
    )
    executor: Mapped[str] = mapped_column(
        String(20), server_default=text("'IN_HOUSE'"), nullable=False
    )
    # outward_challan / inward_challan: plain UUID columns with no FK
    # enforcement (ORM or DB) — TASK-CUT-305 dropped the original target
    # tables CASCADE, taking the DB-level FK with them. A future task will
    # model the new jobwork target tables and re-add the FK.
    outward_challan_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    inward_challan_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    qty_rejected: Mapped[Any] = mapped_column(
        Numeric(15, 4), server_default=text("0"), nullable=False
    )
    qty_wastage: Mapped[Any] = mapped_column(
        Numeric(15, 4), server_default=text("0"), nullable=False
    )
    qty_byproduct: Mapped[Any] = mapped_column(
        Numeric(15, 4), server_default=text("0"), nullable=False
    )
    cost_accrued: Mapped[Any] = mapped_column(
        Numeric(18, 2), server_default=text("0"), nullable=False
    )
    rework_of_mo_operation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("mo_operation.mo_operation_id", ondelete="SET NULL"),
        nullable=True,
    )
    is_rework_paid: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    expected_return_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    acknowledged_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    # TR-A07 polish: dedicated counter for "how many times has record_qty_in
    # been called against this op?". The service uses 0 → "first call,
    # overwrite the planning figure" and >0 → "subsequent call, add to the
    # cumulative". Originally the first-call branch was detected by counting
    # OPERATION_QTY_IN_RECORDED events; that heuristic broke as soon as any
    # other code path emitted the same event_type. Counter column = single
    # source of truth.
    qty_in_record_count: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), nullable=False
    )
    # TR-A08 followup: per-op input / output item. ``input_item_id`` is the
    # item this operation consumes (== the prior op's ``output_item_id``,
    # or the BOM's primary raw for the first op); ``output_item_id`` is
    # the item this operation produces (== MO's finished item in v1).
    # Both NULLABLE — legacy rows created pre-followup carry NULL.
    # Karigar dispatch picks ``input_item_id`` (not MO.finished_item_id)
    # so multi-stage routings dispatch the right physical item.
    input_item_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("item.item_id", ondelete="RESTRICT"),
        nullable=True,
    )
    output_item_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("item.item_id", ondelete="RESTRICT"),
        nullable=True,
    )

    manufacturing_order: Mapped[ManufacturingOrder] = relationship(back_populates="operations")
    # Lazy join to the catalogue row so reason strings / UI can render
    # the operation's human name without a separate lookup. Selectinload-
    # eligible via ``selectinload(MoOperation.operation_master)``; the
    # routing_flow engine uses that to surface FE-friendly predecessor
    # names in its blocked-reason strings (TR-A09 FU3).
    operation_master: Mapped[OperationMaster] = relationship()


# ──────────────────────────────────────────────────────────────────────
# Material issue — raw material issued from stock against an MO (TR-A06)
# ──────────────────────────────────────────────────────────────────────


class MaterialIssue(Base, TimestampMixin, SoftDeleteMixin):
    """One issue of raw material(s) against an MO. Header carries the
    issue number, MO reference, and the GL voucher posted for the
    DR WIP / CR Inventory move. Lines (``MaterialIssueLine``) carry the
    per-component qty / lot / cost detail.

    Per-firm numbering (``UNIQUE (org_id, firm_id, series, number)``).
    ``audit-sweep`` shape — ``created_by`` declared inline (FK to
    ``app_user``) per the migration; ``updated_by`` plain UUID via the
    sweep equivalent.
    """

    __tablename__ = "material_issue"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "firm_id",
            "series",
            "number",
            name="material_issue_org_firm_series_number_key",
        ),
    )

    material_issue_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=False,
    )
    manufacturing_order_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("manufacturing_order.manufacturing_order_id", ondelete="RESTRICT"),
        nullable=False,
    )
    series: Mapped[str] = mapped_column(String(50), nullable=False)
    number: Mapped[str] = mapped_column(String(50), nullable=False)
    issue_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    narration: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The posted GL voucher for this issue (DR WIP / CR Inventory).
    # Nullable for forward-compat / admin imports; the service always
    # writes a voucher in v1.
    voucher_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("voucher.voucher_id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )

    lines: Mapped[list[MaterialIssueLine]] = relationship(
        back_populates="material_issue",
        cascade="all, delete-orphan",
        order_by="MaterialIssueLine.created_at",
    )


class MaterialIssueLine(Base, TimestampMixin, SoftDeleteMixin):
    """One issued component on a ``MaterialIssue``. ``line_value`` is
    persisted (``qty * unit_cost``) so a later reprint can show the
    historical valuation even if ``stock_position.current_cost`` has
    drifted since.

    ``stock_ledger_id`` is a plain UUID (no FK) — same posture as
    ``mo_operation.outward_challan_id``: the ledger is append-only and
    we never want a CASCADE-from-delete on this column.
    """

    __tablename__ = "material_issue_line"

    material_issue_line_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    material_issue_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("material_issue.material_issue_id", ondelete="CASCADE"),
        nullable=False,
    )
    mo_material_line_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("mo_material_line.mo_material_line_id", ondelete="RESTRICT"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("item.item_id", ondelete="RESTRICT"),
        nullable=False,
    )
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("lot.lot_id", ondelete="RESTRICT"),
        nullable=True,
    )
    qty_issued: Mapped[Any] = mapped_column(Numeric(15, 4), nullable=False)
    unit_cost: Mapped[Any | None] = mapped_column(Numeric(15, 6), nullable=True)
    line_value: Mapped[Any] = mapped_column(Numeric(18, 2), nullable=False)
    stock_ledger_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    material_issue: Mapped[MaterialIssue] = relationship(back_populates="lines")


# ──────────────────────────────────────────────────────────────────────
# Production event — append-only, idempotent event log
# ──────────────────────────────────────────────────────────────────────


class ProductionEvent(Base):
    """Append-only, idempotent event log for the Manufacturing module.

    Idempotent via `idempotency_key` (partial-unique on
    `(org_id, idempotency_key)`); supports replay, projections, audit.
    DDL ships `occurred_at` (business timestamp, can be backdated) and
    `created_at` (server receipt). Explicitly *exempt* from the audit
    sweep — no `updated_at` / `updated_by` / `deleted_at`.
    """

    __tablename__ = "production_event"

    event_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=False,
    )
    manufacturing_order_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("manufacturing_order.manufacturing_order_id", ondelete="RESTRICT"),
        nullable=True,
    )
    mo_operation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("mo_operation.mo_operation_id", ondelete="RESTRICT"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_party_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("party.party_id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    occurred_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    prev_event_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    event_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


__all__ = [
    "Bom",
    "BomLine",
    "Design",
    "ManufacturingOrder",
    "MaterialIssue",
    "MaterialIssueLine",
    "MoMaterialLine",
    "MoOperation",
    "MoOperationState",
    "MoStatus",
    "MoType",
    "OperationMaster",
    "OperationType",
    "ProductionEvent",
    "Routing",
    "RoutingEdge",
    "RoutingEdgeType",
]

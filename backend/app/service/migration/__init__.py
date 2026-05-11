"""Migration adapter package — Protocol + intermediate format (TASK-CUT-305 Half A).

This package defines the contract that every external-data adapter (Vyapar
in Wave 5 via TASK-CUT-402, Tally / generic Excel in v2) implements. Wave 5
ships the actual Vyapar parser; this package only fixes the shape so the
parser drops in without any cross-cutting refactors.

Public surface:

- ``MigrationAdapter`` — structural Protocol every adapter conforms to.
- ``IntermediateParty`` — canonical party row produced by adapters.
- ``IntermediateOpeningBalance`` — canonical opening-balance row.
- ``MigrationValidationReport`` — what ``validate()`` returns.
- ``ReconciliationRow`` — one row inside the validation report.
- ``NoopMigrationAdapter`` — a zero-op adapter used by tests and as the
  reference for the Protocol's structural shape.

v1 scope is exactly what the cutover plan locked: parties + opening
ledger balances. Transaction history stays in the source system for
historical lookup. Do not extend this contract speculatively — TASK-CUT-402
is the only consumer planned for v1.
"""

from __future__ import annotations

from .intermediate import (
    IntermediateOpeningBalance,
    IntermediateParty,
    MigrationValidationReport,
    ReconciliationRow,
)
from .noop_adapter import NoopMigrationAdapter
from .protocol import MigrationAdapter

__all__ = [
    "IntermediateOpeningBalance",
    "IntermediateParty",
    "MigrationAdapter",
    "MigrationValidationReport",
    "NoopMigrationAdapter",
    "ReconciliationRow",
]

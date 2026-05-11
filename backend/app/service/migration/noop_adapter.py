"""NoopMigrationAdapter — the zero-row stub used by tests and the FE preview.

Why this exists:

1. **Reference implementation of the Protocol.** Anyone implementing a new
   adapter can look at this file and see what shape ``extract_parties`` and
   ``validate`` are supposed to have without first reading the Protocol's
   abstract methods.

2. **Hooks the test in ``test_migration_protocol.py``.** The test asserts
   ``isinstance(NoopMigrationAdapter(), MigrationAdapter)`` — the structural
   conformance proof. Without a concrete instance to point at, the Protocol
   would be a dead letter until Wave 5 wired the Vyapar adapter.

3. **Default for the FE preview pane (future, Wave 5).** Before the user
   uploads a real file, the migration screen renders an empty preview;
   ``NoopMigrationAdapter().validate(None)`` returns "0 parties, 0 OBs"
   so the screen has something to draw.

What this is NOT:

- Not a Vyapar parser. That's TASK-CUT-402.
- Not a Tally parser. That's a future v2 task.
- Not a generic Excel parser. Also v2.
- Not registered in the API router. ``POST /admin/migrations`` ships in Wave 5
  alongside the Vyapar adapter.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .intermediate import (
    IntermediateOpeningBalance,
    IntermediateParty,
    MigrationValidationReport,
    ReconciliationRow,
)


class NoopMigrationAdapter:
    """Adapter that always emits zero rows.

    Conforms structurally to ``MigrationAdapter`` (verified by
    ``test_migration_protocol.py``). Useful as:

    - A stub in tests that need a non-None adapter.
    - A starting template for new adapters (copy + replace the bodies).
    - The default the FE preview pane uses pre-upload.

    Accepts any ``source`` shape — the parameter is ignored.
    """

    def extract_parties(self, source: Any) -> Iterable[IntermediateParty]:
        """Always yields nothing. ``source`` is accepted for signature parity."""
        _ = source
        return iter(())

    def extract_opening_balances(self, source: Any) -> Iterable[IntermediateOpeningBalance]:
        """Always yields nothing. ``source`` is accepted for signature parity."""
        _ = source
        return iter(())

    def validate(self, source: Any) -> MigrationValidationReport:
        """Return a fixed empty report.

        Emits one ``info`` reconciliation row so downstream code that
        renders the row list has something to draw on a fresh-upload
        screen (rather than an empty array that looks like a render
        bug).
        """
        _ = source
        return MigrationValidationReport(
            total_parties=0,
            total_opening_balances=0,
            errors=0,
            warnings=0,
            rows=(
                ReconciliationRow(
                    severity="info",
                    code="NOOP",
                    message="No source loaded; using NoopMigrationAdapter (extracts zero rows).",
                    source_ref=None,
                ),
            ),
            tb_reconciles=None,
            tb_diff=None,
        )


__all__ = ["NoopMigrationAdapter"]

"""``MigrationAdapter`` Protocol — what every external-data adapter implements.

This is a *structural* Protocol (PEP 544 / ``runtime_checkable``). Adapters
do not subclass it; they just expose methods with the right signatures and
``isinstance(adapter, MigrationAdapter)`` evaluates True. This keeps Wave 5's
``VyaparExcelAdapter`` decoupled from this package — it sits next to its
column-mapping YAML and only depends on the intermediate-format types.

Per CLAUDE.md decision #5: Vyapar is the primary adapter (Wave 5), Tally XML
and generic Excel are siblings (v2). All three implement this Protocol, so
the wrapping ``commit_to_db`` call site has one shape to handle.

v1 scope is parties + opening balances only (cutover plan §"Migration:
minimum"). Three methods cover it:

- ``extract_parties``    — produces ``Iterable[IntermediateParty]``
- ``extract_opening_balances`` — produces ``Iterable[IntermediateOpeningBalance]``
- ``validate``           — non-destructive pass, returns a report

``source`` is intentionally typed as ``Any`` — the adapter knows whether
its source is a file path, an in-memory ``BytesIO``, or a parsed object.
The wrapping API endpoint (Wave 5: ``POST /admin/migrations``) figures
out the right shape per ``content_type`` before handing off.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

from .intermediate import (
    IntermediateOpeningBalance,
    IntermediateParty,
    MigrationValidationReport,
)


@runtime_checkable
class MigrationAdapter(Protocol):
    """Structural type every migration adapter conforms to.

    Adapters are stateless transformers — they read the source and emit
    intermediate rows. They do NOT write to Postgres; the wrapping
    commit step (Wave 5) handles RLS / FK resolution / TB reconciliation.

    Concrete adapters implement these as plain methods (no superclass
    required). The ``runtime_checkable`` decorator means tests can assert
    structural conformance via ``isinstance(adapter, MigrationAdapter)``.
    """

    def extract_parties(self, source: Any) -> Iterable[IntermediateParty]:
        """Yield every party row from ``source``.

        Order matters only for human-readable reconciliation. The commit
        step does not assume any particular order. Adapter MUST emit a
        unique ``source_id`` per row — duplicates are flagged as errors
        by ``validate``.
        """
        ...

    def extract_opening_balances(self, source: Any) -> Iterable[IntermediateOpeningBalance]:
        """Yield every opening-balance row from ``source``.

        For party-scoped balances (sundry debtors / creditors), the
        ``party_source_id`` MUST match an ``IntermediateParty.source_id``
        from ``extract_parties``. Cross-referencing is the commit step's
        job; the adapter just needs to be consistent across calls.

        Firm-level OBs (cash, capital, bank) use ``party_source_id=None``.
        """
        ...

    def validate(self, source: Any) -> MigrationValidationReport:
        """Run a non-destructive pass over ``source`` and return findings.

        This is the dry-run the user sees BEFORE clicking "Approve" on
        the migration. The report MUST be safe to compute multiple times
        on the same source — no side effects, no DB writes, no temp
        files left behind.

        Errors / warnings here block ("error") or merely annotate ("warn")
        the commit step. The TB-reconciliation fields are populated by
        the commit step itself; adapters leave them at their defaults
        unless they can cheaply pre-compute them (e.g. a balanced TB
        export that already sums to zero).
        """
        ...


__all__ = ["MigrationAdapter"]

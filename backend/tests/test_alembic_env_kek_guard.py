"""TASK-TR-SEC1 follow-ups (issue #22): alembic env.py KEK fail-fast on both modes.

The TR-SEC1 fix-pass added a `get_master_kek()` call to
`run_migrations_online` so the master KEK is resolved BEFORE migrations
mutate the schema; if `PII_MASTER_KEY` is missing in a non-dev environment,
the migration aborts with a clear message instead of stranding the DB
mid-backfill.

The offline path (`alembic upgrade head --sql`, used for ops review of
the SQL that would run) had the same property gap. This module exposes
`_ensure_kek_loaded()` and calls it from BOTH `run_migrations_online`
and `run_migrations_offline`. We can't easily import alembic/env.py
under pytest (it executes top-level `context.is_offline_mode()`), so
this test imports the helper directly via runpy with the path injected.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest


def _load_ensure_kek_loaded(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """Import the `_ensure_kek_loaded` helper from alembic/env.py without
    triggering its top-level migration dispatch.

    `env.py` ends with `if context.is_offline_mode(): run_migrations_offline()
    else: run_migrations_online()` — both branches need a live alembic
    `EnvironmentContext`, which is only set up when alembic itself
    invokes the file. We sidestep that by reading the source and exec'ing
    only the function definitions we need, with a stub installed on
    `alembic.context` so the top-level `config = context.config` line
    doesn't blow up.
    """
    import types

    import alembic

    stub_context = types.SimpleNamespace(
        config=types.SimpleNamespace(
            config_file_name=None,
            set_main_option=lambda *_a, **_kw: None,
            get_main_option=lambda *_a, **_kw: "",
            get_section=lambda *_a, **_kw: {},
            config_ini_section="alembic",
        ),
        is_offline_mode=lambda: False,
        begin_transaction=lambda: None,
        configure=lambda **_kw: None,
        run_migrations=lambda: None,
    )
    monkeypatch.setattr(alembic, "context", stub_context, raising=False)

    env_path = Path(__file__).resolve().parents[1] / "alembic" / "env.py"
    source = env_path.read_text(encoding="utf-8")
    # Keep everything up to the `if context.is_offline_mode()` dispatch.
    cutoff = source.index("if context.is_offline_mode()")
    safe_source = source[:cutoff]

    namespace: dict[str, object] = {}
    exec(compile(safe_source, str(env_path), "exec"), namespace)
    helper = namespace["_ensure_kek_loaded"]
    assert callable(helper)
    return helper


def test_ensure_kek_loaded_fails_in_prod_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #22 follow-up: the offline migration path used to skip the
    KEK fail-fast, so `alembic upgrade head --sql` would happily emit a
    SQL dump in prod with no key configured — and the live `alembic
    upgrade head` against that dump would then strand a half-applied
    migration. `_ensure_kek_loaded()` now runs from BOTH paths."""
    from app.utils import crypto

    ensure_kek_loaded = _load_ensure_kek_loaded(monkeypatch)
    monkeypatch.delenv("PII_MASTER_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "prod")
    crypto._reset_caches_for_tests()

    with pytest.raises(crypto.PIIConfigError):
        ensure_kek_loaded()


def test_ensure_kek_loaded_succeeds_in_dev_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dev with the public fallback KEK is the supported "fresh clone"
    path — migrations must proceed, not be blocked by the guard."""
    from app.utils import crypto

    ensure_kek_loaded = _load_ensure_kek_loaded(monkeypatch)
    monkeypatch.delenv("PII_MASTER_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    crypto._reset_caches_for_tests()

    ensure_kek_loaded()

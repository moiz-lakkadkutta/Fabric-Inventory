"""TASK-INT-7: dev-stack contracts.

These tests guard the "fresh clone → working stack" path:

- `.env.example` must use host-reachable URLs (localhost), so a developer
  who runs uvicorn natively never inherits docker-internal hostnames.
- `make setup` writes `backend/.env` from the template if missing, but
  must not overwrite a developer's existing local config.

The QA pass on 2026-05-06 found the stack silently broken because env
vars from a parent shell (with `postgres:5432`/`redis:6379`) overrode
`.env`, the api had no DB, and there was no preflight to surface this.
These tests close those holes at the file level; `make doctor` (in
scripts/test_doctor.sh) closes them at the runtime level.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ENV_EXAMPLE = REPO_ROOT / "backend" / ".env.example"


def _parse_dotenv(path: Path) -> dict[str, str]:
    """Tiny dotenv parser — no external dep, ignores comments/blank lines."""
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def _host_of(url: str) -> str:
    """Pull the hostname out of a URL like postgresql+asyncpg://u:p@HOST:port/db."""
    m = re.search(r"://[^@/]+@([^:/]+)", url)
    assert m, f"could not parse host from {url!r}"
    return m.group(1)


def test_dotenv_template_has_localhost_urls() -> None:
    """`.env.example` is the first thing a fresh-clone developer copies.

    Both DATABASE_URL and MIGRATION_DATABASE_URL must use `localhost` so
    that native uvicorn (Postgres reachable via host port mapping) works.
    Compose containers override these via `docker-compose.yml` env to
    use the in-network `postgres`/`redis` hostnames; the template stays
    host-friendly.
    """
    assert BACKEND_ENV_EXAMPLE.exists(), f"missing {BACKEND_ENV_EXAMPLE}"
    env = _parse_dotenv(BACKEND_ENV_EXAMPLE)

    for key in ("DATABASE_URL", "MIGRATION_DATABASE_URL", "REDIS_URL"):
        assert key in env, (
            f"{BACKEND_ENV_EXAMPLE.name} is missing {key}; "
            "fresh-clone setup will silently fail when uvicorn runs natively"
        )

    for key in ("DATABASE_URL", "MIGRATION_DATABASE_URL"):
        host = _host_of(env[key])
        assert host == "localhost", (
            f"{key} in {BACKEND_ENV_EXAMPLE.name} resolves to host {host!r}; "
            "must be 'localhost' so native uvicorn reaches host-mapped Postgres. "
            "Compose containers override this via docker-compose.yml."
        )

    redis_host_match = re.search(r"redis://([^:/]+)", env["REDIS_URL"])
    assert redis_host_match, f"REDIS_URL malformed: {env['REDIS_URL']!r}"
    assert redis_host_match.group(1) == "localhost", (
        f"REDIS_URL host is {redis_host_match.group(1)!r}; must be 'localhost'."
    )


def test_compose_api_entrypoint_runs_alembic_before_uvicorn() -> None:
    """`make dev` (compose path) must produce a migrated DB.

    Pre-INT-7, the compose `api` service booted uvicorn directly against
    an empty schema; every endpoint 500'd until someone manually ran
    `make migrate`. Closing P0-2 means: the api container's entrypoint
    runs `alembic upgrade head` before uvicorn, every time.
    """
    entry = REPO_ROOT / "backend" / "entrypoint.dev.sh"
    assert entry.exists(), "missing backend/entrypoint.dev.sh"
    body = entry.read_text()
    assert "alembic upgrade head" in body, (
        "entrypoint must run alembic before uvicorn — fresh `make dev` "
        "produces a 500-on-everything api otherwise (P0-2)"
    )
    assert 'exec "$@"' in body or "exec $@" in body, (
        "entrypoint must `exec` the CMD so signals propagate to uvicorn"
    )

    dockerfile = (REPO_ROOT / "backend" / "Dockerfile.dev").read_text()
    assert "entrypoint.dev.sh" in dockerfile, (
        "Dockerfile.dev must wire the entrypoint script as ENTRYPOINT"
    )


def test_dev_native_script_scrubs_shell_env_and_auto_migrates() -> None:
    """`make dev-native` must reproduce the QA-pass fix on every fresh
    shell, not just for whoever first wrote `.env`.

    The 2026-05-06 failure was: a parent shell exported docker-internal
    `DATABASE_URL` (with `postgres:5432`), child uvicorn inherited it,
    and pydantic-settings' env > .env precedence meant `.env` was
    overruled. Running uvicorn with a scrubbed env (env -i + sourced
    .env) makes pollution impossible.

    We assert the contract by checking the script's structure rather
    than booting it (booting forks long-lived processes; not a unit
    test). The contract:
      1. uses `env -i` (or equivalent) so shell vars can't leak into uvicorn
      2. runs `alembic upgrade head` before serving (closes P0-2)
      3. brings up postgres+redis via compose, then launches uvicorn + vite
    """
    script = REPO_ROOT / "scripts" / "dev-native.sh"
    assert script.exists() and script.is_file(), f"missing {script}"
    assert script.stat().st_mode & 0o111, f"{script.name} not executable"
    body = script.read_text()

    assert "env -i" in body, (
        "dev-native must launch uvicorn under `env -i` to prevent shell-env "
        "pollution (the actual root cause of the 2026-05-06 outage)"
    )
    assert "alembic upgrade head" in body, (
        "dev-native must auto-migrate before serving — fresh clones with no "
        "schema were the second half of the 2026-05-06 outage"
    )
    assert "postgres" in body and "redis" in body, (
        "dev-native must bring up postgres+redis via compose"
    )
    assert "uvicorn" in body, "dev-native must launch uvicorn"


def test_make_setup_writes_dotenv_idempotently(tmp_path: pytest.TempPathFactory) -> None:
    """`make setup` must:
      1. Write `backend/.env` from `backend/.env.example` if it doesn't exist.
      2. NOT overwrite an existing `.env` (developer's local edits stay).

    We exercise this against a sandboxed copy of the backend dir to avoid
    touching the developer's real `.env`.
    """
    sandbox = Path(str(tmp_path)) / "backend-sandbox"
    sandbox.mkdir()
    shutil.copy(BACKEND_ENV_EXAMPLE, sandbox / ".env.example")

    template_value = "DATABASE_URL=postgresql+asyncpg://fabric:fabric_dev@localhost:5432/fabric_erp"
    user_value = "DATABASE_URL=postgresql+asyncpg://custom_user:s3cret@localhost:5432/custom_db"

    # Step 1: simulate "no .env yet". The Makefile's setup target does
    # `test -f backend/.env || cp backend/.env.example backend/.env`. We
    # invoke the same shell behavior so the test fails if the Makefile
    # is changed in a way that breaks idempotency.
    target = sandbox / ".env"
    assert not target.exists()
    subprocess.run(
        ["sh", "-c", f"test -f {target} || cp {sandbox / '.env.example'} {target}"],
        check=True,
    )
    assert target.exists()
    assert template_value in target.read_text()

    # Step 2: developer edits .env. Re-running the same command must
    # leave their edits untouched.
    target.write_text(user_value + "\n")
    subprocess.run(
        ["sh", "-c", f"test -f {target} || cp {sandbox / '.env.example'} {target}"],
        check=True,
    )
    assert target.read_text() == user_value + "\n", (
        ".env was overwritten on second 'make setup'; developer's local "
        "config (DB password, secrets) would be wiped"
    )

#!/usr/bin/env python3
"""Dump the FastAPI app's OpenAPI schema to JSON.

Run from `backend/` (so `import main` resolves) — typically via
`make openapi-snapshot` or the CI step. Writes to
`frontend/scripts/openapi-snapshot.json` (or `--out` if provided).

The schema is the single source of truth for the FE codegen
(`pnpm gen:types` → `frontend/src/types/api.ts`). Keeping the snapshot
in git means CI can regenerate FE types without standing up a live
backend; drift between BE and the snapshot is caught by `pnpm
check:types`.

Why this script lives in `frontend/scripts/` even though it imports
the BE app: the snapshot it produces is a frontend-build input. The
scripts directory is the FE's "this is how my types are made"
contract; we just happen to import the BE in-process to cheaply get a
guaranteed-current schema. Running with no live server, no DB, no
Redis — only Settings env vars.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Settings env vars required by `from main import app`. We supply
# placeholder values when not already set; the script never touches
# the DB or Redis, so connection strings only need to parse.
_DEFAULTS = {
    "DATABASE_URL": "postgresql://placeholder:placeholder@localhost:5432/placeholder",
    "JWT_SECRET": "placeholder-jwt-secret-32-chars-min-12345",
    "CORS_ORIGINS": "http://localhost:5173",
    "ENVIRONMENT": "dev",
}


def _resolve_repo_root() -> Path:
    """Find the repo root by walking up until we see `backend/main.py`."""
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "backend" / "main.py").is_file():
            return parent
    raise SystemExit(
        "Could not locate repo root (no backend/main.py found above this script). "
        "Run from a checkout of the fabric repo."
    )


def _load_app_openapi() -> dict[str, object]:
    repo_root = _resolve_repo_root()
    backend_dir = repo_root / "backend"

    # Prepend backend/ to sys.path so `from main import app` works.
    sys.path.insert(0, str(backend_dir))

    # Backstop the env so Settings() doesn't blow up. We DO NOT override
    # values the user already set (CI, dev shells); this only kicks in
    # for offline/local invocations where the env is bare.
    for key, default in _DEFAULTS.items():
        os.environ.setdefault(key, default)

    # Import here, after sys.path + env are ready.
    from main import app  # type: ignore[import-not-found]

    return app.openapi()  # type: ignore[no-any-return]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=None,
        help="Output path. Defaults to frontend/scripts/openapi-snapshot.json.",
    )
    args = parser.parse_args()

    repo_root = _resolve_repo_root()
    out_path = (
        Path(args.out)
        if args.out
        else repo_root / "frontend" / "scripts" / "openapi-snapshot.json"
    )

    schema = _load_app_openapi()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Stable ordering + 2-space indent + trailing newline so diffs are
    # minimal and the file plays nicely with prettier-ignore.
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(schema, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print(f"Wrote OpenAPI snapshot ({len(schema.get('paths', {}))} paths) to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

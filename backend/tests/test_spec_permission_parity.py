"""Q01-12 guard: the OpenAPI spec matches the routes and permissions the code enforces.

CLAUDE.md: "Don't add endpoints without OpenAPI spec ... with the endpoint,
parameters, and `x-permission`." This walks ``app.routes`` and reads the
permission each route enforces from its ``require_permission(...)`` dependency,
the same way the Q01 permission matrix was built. Routes with no permission are
``public``, or ``authenticated`` when they depend on ``get_current_user``.

The code is the source of truth. When this fails, fix the spec, not the route:
``cd backend && uv run python -m scripts.spec_sync --write`` (then review the diff).
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]  # PyYAML ships via uvicorn[standard]; no stubs
from fastapi import FastAPI

from scripts.spec_sync import (
    AUTHENTICATED,
    PUBLIC,
    SPEC_DIR,
    drift,
    enforced_permissions,
    load_spec,
    spec_operations,
)


@pytest.fixture(scope="module")
def app() -> FastAPI:
    from main import create_app

    return create_app()


@pytest.fixture(scope="module")
def ops() -> dict[tuple[str, str], dict[str, Any]]:
    return spec_operations(load_spec())


def test_permission_extraction_reads_the_enforced_code(app: FastAPI) -> None:
    """Sanity: the walker sees real permissions, so the parity check is not vacuous."""
    enforced = enforced_permissions(app)
    assert len(enforced) >= 150, f"route walk looks vacuous: {len(enforced)} routes"
    assert enforced[("POST", "/parties")] == "masters.party.create"
    assert enforced[("DELETE", "/designs/{design_id}")] == "manufacturing.design.delete"
    assert enforced[("POST", "/auth/login")] == PUBLIC
    assert enforced[("GET", "/auth/me")] == AUTHENTICATED
    assert sum(1 for p in enforced.values() if p not in (PUBLIC, AUTHENTICATED)) >= 150


def test_every_route_is_in_the_spec_with_the_enforced_permission(
    app: FastAPI, ops: dict[tuple[str, str], dict[str, Any]]
) -> None:
    problems = drift(enforced_permissions(app), ops)
    report = {k: v for k, v in problems.items() if v}
    assert not report, (
        "specs/api-phase1.yaml has drifted from the routes "
        "(run `uv run python -m scripts.spec_sync --write`):\n"
        + "\n".join(f"{title} ({len(items)}): {items}" for title, items in report.items())
    )


class _StrictLoader(yaml.SafeLoader):  # type: ignore[misc]
    """SafeLoader that refuses duplicate keys (a duplicate path would hide operations)."""


def _no_duplicate_keys(loader: _StrictLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    keys = [loader.construct_object(k) for k, _ in node.value]
    dupes = sorted({str(k) for k in keys if keys.count(k) > 1})
    assert not dupes, f"duplicate keys {dupes} at line {node.start_mark.line + 1}"
    mapping: dict[Any, Any] = loader.construct_mapping(node)
    return mapping


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys)


@pytest.mark.parametrize("spec_file", sorted(SPEC_DIR.glob("*.yaml")), ids=lambda p: p.name)
def test_every_spec_file_is_valid_yaml(spec_file: Any) -> None:
    with spec_file.open(encoding="utf-8") as fh:
        data = yaml.load(fh, Loader=_StrictLoader)  # a SafeLoader subclass
    assert isinstance(data, dict) and "openapi" in data and "paths" in data


@pytest.mark.parametrize(
    "path",
    ["/designs/{design_id}", "/boms/{bom_id}", "/operation-masters/{operation_master_id}"],
)
def test_master_delete_documents_204_and_422_in_use(
    path: str, ops: dict[tuple[str, str], dict[str, Any]]
) -> None:
    """FUP-205-C(2): deleting a referenced master is refused with 422, not 409/404."""
    op = ops.get(("DELETE", path))
    assert op is not None, f"DELETE {path} missing from specs/api-phase1.yaml"
    responses = op["responses"]
    assert "204" in responses
    assert "in use" in responses["422"]["description"].lower()

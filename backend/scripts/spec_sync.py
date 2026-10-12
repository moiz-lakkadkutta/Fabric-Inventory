"""Keep ``specs/api-phase1.yaml`` in step with the routes the app serves (Q01-12).

The code is the source of truth. ``x-permission`` on every operation must be the
permission its route enforces through ``require_permission(...)``. Routes without
one are ``public`` or ``authenticated`` (they depend on ``get_current_user``).

* ``uv run python -m scripts.spec_sync``: report the drift (exit 1 if any).
* ``uv run python -m scripts.spec_sync --write``: fix the spec in place.

``--write`` edits the YAML line by line so the hand-written operations keep their
formatting and comments. It:

1. renames a spec path whose parameter names differ from the route's
   (``/purchase-invoices/{purchase_invoice_id}`` becomes ``/purchase-invoices/{pi_id}``);
2. rewrites each wrong ``x-permission`` to the enforced code;
3. marks spec operations with no route ``x-implemented: false`` (planned, not
   served) and drops the marker once a route exists;
4. appends an operation for each route the spec lacks, generated from the app's
   own OpenAPI. Schemas are referenced in ``frontend/scripts/openapi-snapshot.json``
   (kept current by ``make openapi-snapshot`` and CI's openapi-drift job) rather than
   copied.

The guard is ``tests/test_spec_permission_parity.py``.
"""

from __future__ import annotations

import argparse
import copy
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]  # PyYAML ships via uvicorn[standard]; no stubs
from fastapi import FastAPI
from fastapi.routing import APIRoute

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_DIR = REPO_ROOT / "specs"
SPEC_PATH = SPEC_DIR / "api-phase1.yaml"
SNAPSHOT_REF = "../frontend/scripts/openapi-snapshot.json"

PUBLIC = "public"
AUTHENTICATED = "authenticated"
HTTP_METHODS = ("get", "put", "post", "patch", "delete")
_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

RouteKey = tuple[str, str]  # (METHOD, path)

_PATH_LINE = re.compile(r"^  (/\S*):\s*$")
_METHOD_LINE = re.compile(r"^    (get|put|post|patch|delete):\s*$")
_XPERM_LINE = re.compile(r"^      x-permission:.*$")
_XIMPL_LINE = re.compile(r"^      x-implemented:.*$")
_PARAM = re.compile(r"\{[^}]+\}")


# ── Enforced side (the code) ──────────────────────────────────────────


def _walk_dependencies(route: APIRoute) -> Iterable[Any]:
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        yield dep
        stack.extend(dep.dependencies)


def _permission_code(dep_call: Any) -> str:
    """The ``permission_code`` captured by a ``require_permission(code)`` closure."""
    code = dep_call.__code__
    cells = dict(zip(code.co_freevars, dep_call.__closure__ or (), strict=True))
    value = cells["permission_code"].cell_contents
    assert isinstance(value, str)
    return value


def route_permission(route: APIRoute) -> str:
    codes: set[str] = set()
    authenticated = False
    for dep in _walk_dependencies(route):
        qualname = getattr(dep.call, "__qualname__", "")
        if qualname.startswith("require_permission."):
            codes.add(_permission_code(dep.call))
        elif qualname == "get_current_user":
            authenticated = True
    if codes:
        return " + ".join(sorted(codes))
    return AUTHENTICATED if authenticated else PUBLIC


def enforced_permissions(app: FastAPI) -> dict[RouteKey, str]:
    """``{(METHOD, path): x-permission}`` for every API route the app serves."""
    out: dict[RouteKey, str] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            out[(method, route.path)] = route_permission(route)
    return out


def _routes_by_key(app: FastAPI) -> dict[RouteKey, APIRoute]:
    out: dict[RouteKey, APIRoute] = {}
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods - {"HEAD", "OPTIONS"}:
                out[(method, route.path)] = route
    return out


# ── Spec side ─────────────────────────────────────────────────────────


def load_spec(path: Path = SPEC_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict)
    return data


def spec_operations(spec: dict[str, Any]) -> dict[RouteKey, dict[str, Any]]:
    out: dict[RouteKey, dict[str, Any]] = {}
    for path, item in (spec.get("paths") or {}).items():
        for method in HTTP_METHODS:
            if isinstance(item, dict) and method in item:
                out[(method.upper(), path)] = item[method]
    return out


def drift(
    enforced: dict[RouteKey, str], ops: dict[RouteKey, dict[str, Any]]
) -> dict[str, list[str]]:
    """Every way the spec disagrees with the code, as readable lines."""
    missing = [
        f"{m} {p} (enforces {perm})"
        for (m, p), perm in sorted(enforced.items())
        if (m, p) not in ops
    ]
    wrong = [
        f"{m} {p}: spec says {ops[(m, p)].get('x-permission')!r}, code enforces {perm!r}"
        for (m, p), perm in sorted(enforced.items())
        if (m, p) in ops and ops[(m, p)].get("x-permission") != perm
    ]
    unmarked = [
        f"{m} {p}"
        for (m, p), op in sorted(ops.items())
        if (m, p) not in enforced and op.get("x-implemented") is not False
    ]
    stale = [
        f"{m} {p}"
        for (m, p), op in sorted(ops.items())
        if (m, p) in enforced and "x-implemented" in op
    ]
    return {
        "routes missing from the spec": missing,
        "wrong x-permission": wrong,
        "spec operations with no route and no `x-implemented: false`": unmarked,
        "`x-implemented` marker on an operation that is served": stale,
    }


# ── Line-level YAML editing ───────────────────────────────────────────


class _Index:
    """Line ranges of the path items and operations under ``paths:``."""

    def __init__(self, lines: list[str]) -> None:
        start = lines.index("paths:\n") + 1
        self.paths: dict[str, tuple[int, int]] = {}
        self.ops: dict[RouteKey, tuple[int, int]] = {}
        current_path: str | None = None
        path_start = 0
        op_key: RouteKey | None = None
        op_start = 0
        end = len(lines)
        for i in range(start, len(lines)):
            line = lines[i]
            if line.strip() and not line.startswith(" "):
                end = i  # a later top-level key ends ``paths:``
                break
            pm = _PATH_LINE.match(line)
            mm = _METHOD_LINE.match(line)
            if (pm or mm) and op_key is not None:
                self.ops[op_key] = (op_start, i)
                op_key = None
            if pm:
                if current_path is not None:
                    self.paths[current_path] = (path_start, i)
                current_path, path_start = pm.group(1), i
            elif mm and current_path is not None:
                op_key, op_start = (mm.group(1).upper(), current_path), i
        if op_key is not None:
            self.ops[op_key] = (op_start, end)
        if current_path is not None:
            self.paths[current_path] = (path_start, end)
        self.end = end


def _last_content_line(lines: list[str], start: int, end: int) -> int:
    i = end - 1
    while i > start and not lines[i].strip():
        i -= 1
    return i


def _normalise(path: str) -> str:
    return _PARAM.sub("{}", path)


def _rename_paths(lines: list[str], app_paths: set[str]) -> list[str]:
    idx = _Index(lines)
    by_shape: dict[str, list[str]] = {}
    for p in app_paths:
        by_shape.setdefault(_normalise(p), []).append(p)
    for spec_path, (start, end) in sorted(idx.paths.items(), key=lambda kv: -kv[1][0]):
        if spec_path in app_paths:
            continue
        candidates = by_shape.get(_normalise(spec_path), [])
        if len(candidates) != 1 or candidates[0] in idx.paths:
            continue
        new_path = candidates[0]
        lines[start] = f"  {new_path}:\n"
        for old, new in zip(_PARAM.findall(spec_path), _PARAM.findall(new_path), strict=True):
            old_name, new_name = old[1:-1], new[1:-1]
            pattern = re.compile(rf"^(\s*-?\s*name:\s*){re.escape(old_name)}\s*$")
            for i in range(start + 1, end):
                window = "".join(lines[i : i + 4])
                if pattern.match(lines[i].rstrip("\n")) and "in: path" in window:
                    lines[i] = pattern.sub(rf"\g<1>{new_name}", lines[i].rstrip("\n")) + "\n"
    return lines


def _fix_markers(lines: list[str], enforced: dict[RouteKey, str]) -> list[str]:
    idx = _Index(lines)
    for key, (start, end) in sorted(idx.ops.items(), key=lambda kv: -kv[1][0]):
        block = range(start + 1, end)
        impl_line = next((i for i in block if _XIMPL_LINE.match(lines[i])), None)
        if key in enforced:
            perm_line = next((i for i in block if _XPERM_LINE.match(lines[i])), None)
            new = f"      x-permission: {enforced[key]}\n"
            if perm_line is None:
                lines.insert(_last_content_line(lines, start, end) + 1, new)
            else:
                lines[perm_line] = new
            if impl_line is not None:
                del lines[impl_line]
        elif impl_line is None:
            lines.insert(start + 1, "      x-implemented: false\n")
    return lines


def _rewrite_refs(node: Any) -> Any:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str) and v.startswith("#/components/schemas/"):
                out[k] = SNAPSHOT_REF + v
            else:
                out[k] = _rewrite_refs(v)
        return out
    if isinstance(node, list):
        return [_rewrite_refs(v) for v in node]
    return node


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def _generate_operation(
    key: RouteKey,
    route: APIRoute,
    permission: str,
    app_openapi: dict[str, Any],
    used_ids: set[str],
) -> dict[str, Any]:
    method, path = key
    source = copy.deepcopy(app_openapi.get("paths", {}).get(path, {}).get(method.lower()))
    if source is None:  # route hidden from the app's schema
        source = {
            "summary": route.summary or route.name.replace("_", " ").capitalize(),
            "responses": {str(route.status_code or 200): {"description": "Successful Response"}},
        }
    source = _rewrite_refs(source)
    op_id = _camel(route.name)
    if op_id in used_ids:
        op_id = f"{op_id}{method.capitalize()}"
    used_ids.add(op_id)

    responses: dict[str, Any] = dict(source.get("responses") or {})
    if permission != PUBLIC:
        responses.setdefault("401", {"$ref": "#/components/responses/Unauthorized"})
    if permission not in (PUBLIC, AUTHENTICATED):
        responses.setdefault("403", {"$ref": "#/components/responses/Forbidden"})

    op: dict[str, Any] = {"summary": source.get("summary") or route.name}
    if source.get("description"):
        op["description"] = source["description"]
    op["operationId"] = op_id
    op["tags"] = list(source.get("tags") or route.tags or ["platform"])
    if permission == PUBLIC:
        op["security"] = []
    if source.get("parameters"):
        op["parameters"] = source["parameters"]
    if source.get("requestBody"):
        op["requestBody"] = source["requestBody"]
    op["responses"] = dict(sorted(responses.items()))
    op["x-permission"] = permission
    return op


class _IndentedDumper(yaml.SafeDumper):  # type: ignore[misc]
    """Indent sequences under their key, matching the hand-written spec."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        super().increase_indent(flow, False)


def _dump_operation(method: str, op: dict[str, Any]) -> list[str]:
    body = yaml.dump(
        op,
        Dumper=_IndentedDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=100,
    )
    return [f"    {method.lower()}:\n"] + [f"      {line}\n" for line in body.splitlines()]


def _add_missing(
    lines: list[str],
    missing: list[RouteKey],
    enforced: dict[RouteKey, str],
    routes: dict[RouteKey, APIRoute],
    app_openapi: dict[str, Any],
    used_ids: set[str],
) -> list[str]:
    idx = _Index(lines)
    into_existing: dict[str, list[RouteKey]] = {}
    new_paths: dict[str, list[RouteKey]] = {}
    for key in missing:
        (into_existing if key[1] in idx.paths else new_paths).setdefault(key[1], []).append(key)

    def render(keys: list[RouteKey]) -> list[str]:
        out: list[str] = []
        for key in sorted(keys, key=lambda k: HTTP_METHODS.index(k[0].lower())):
            op = _generate_operation(key, routes[key], enforced[key], app_openapi, used_ids)
            out += ["\n", *_dump_operation(key[0], op)]
        return out

    # Into existing path items, bottom-up so earlier indices stay valid.
    for path in sorted(into_existing, key=lambda p: -idx.paths[p][0]):
        start, end = idx.paths[path]
        at = _last_content_line(lines, start, end) + 1
        lines[at:at] = render(into_existing[path])

    tail: list[str] = []
    for path in sorted(new_paths):
        tail += ["\n", f"  {path}:\n", *render(new_paths[path])[1:]]
    at = _last_content_line(lines, 0, _Index(lines).end) + 1
    lines[at:at] = tail
    return lines


def sync(app: FastAPI, spec_path: Path = SPEC_PATH) -> None:
    enforced = enforced_permissions(app)
    routes = _routes_by_key(app)
    app_openapi = app.openapi()
    lines = spec_path.read_text(encoding="utf-8").splitlines(keepends=True)

    lines = _rename_paths(lines, {p for _, p in enforced})
    lines = _fix_markers(lines, enforced)
    ops = spec_operations(yaml.safe_load("".join(lines)))
    used_ids = {str(op.get("operationId")) for op in ops.values()}
    missing = sorted(k for k in enforced if k not in ops)
    lines = _add_missing(lines, missing, enforced, routes, app_openapi, used_ids)
    spec_path.write_text("".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--write", action="store_true", help="fix specs/api-phase1.yaml")
    args = parser.parse_args(argv)

    from main import create_app

    app = create_app()
    if args.write:
        sync(app)
    problems = drift(enforced_permissions(app), spec_operations(load_spec()))
    count = sum(len(v) for v in problems.values())
    for title, items in problems.items():
        if items:
            print(f"{title} ({len(items)}):")
            for item in items:
                print(f"  {item}")
    print(f"{count} problem(s)")
    return 1 if count else 0


if __name__ == "__main__":
    sys.exit(main())

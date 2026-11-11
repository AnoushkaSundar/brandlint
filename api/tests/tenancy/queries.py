"""Finds tenant models queried without the scoped helpers.

Used by test_unscoped_queries.py. Run `python -m tests.tenancy.queries` from api/ to see
the findings, and add `--update` to rewrite the baseline after queries were converted.

What counts as a query on a tenant model:

- `anything.get(Model, ...)`
- `select(...)`, `update(...)`, `delete(...)` with a tenant model anywhere in its arguments
- `anything.query(...)` with a tenant model in its arguments
- `.join(Model, ...)` or `.outerjoin(Model, ...)` where the joined model is a tenant model
- `.select_from(Model)`, unless the `select(...)` it belongs to already names that model

Not seen: a model passed around as a variable, as `_next_id(session, model, prefix)` in
admin/edits.py does. A static scan can't tell which model it is. Convert those by hand.

A name only counts as a model when it was imported from a `models` module, so a contract
class that shares a model's name (Rule, Fact, Finding...) is left alone.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
APP = REPO / "api" / "app"
BASELINE_PATH = Path(__file__).with_name("unscoped_baseline.json")

# A query that is right without a scope says why, on its line or the line above.
EXEMPT = re.compile(r"#\s*unscoped-ok:\s*\S")

STATEMENTS = {"select", "update", "delete"}
JOINS = {"join", "outerjoin"}
SELECT_FROM = "select_from"
# Findings on the same line sort statements first, then gets, then joins.
ORDER = {
    "select": 0,
    "update": 0,
    "delete": 0,
    "get": 1,
    "query": 1,
    "join": 2,
    "select_from": 2,
}


@dataclass(frozen=True)
class Finding:
    line: int
    kind: str
    models: tuple[str, ...]


def tenant_class_names() -> set[str]:
    """The class name of every model whose table belongs to one organisation."""
    from app.db import Base

    from tests.tenancy.inventory import TENANT_TABLES, model_tables

    model_tables()
    return {
        mapper.class_.__name__
        for mapper in Base.registry.mappers
        if mapper.local_table.name in TENANT_TABLES
    }


def _imports(tree: ast.AST, tenant: set[str]) -> tuple[dict[str, str], set[str]]:
    """Names bound to tenant models, and names bound to a `models` module."""
    models: dict[str, str] = {}
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            from_models = module == "models" or module.endswith(".models")
            for alias in node.names:
                local = alias.asname or alias.name
                if from_models and alias.name in tenant:
                    models[local] = alias.name
                elif alias.name == "models":
                    modules.add(local)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.endswith(".models") and alias.asname:
                    modules.add(alias.asname)
    return models, modules


def scan_source(source: str, tenant: set[str]) -> list[Finding]:
    """Every unscoped query on a tenant model in one file's source, in order."""
    tree = ast.parse(source)
    lines = source.splitlines()
    models, modules = _imports(tree, tenant)

    def model_of(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return models.get(node.id)
        if isinstance(node, ast.Attribute):
            if (
                isinstance(node.value, ast.Name)
                and node.value.id in modules
                and node.attr in tenant
            ):
                return node.attr
            return model_of(node.value)
        return None

    def models_in(*nodes: ast.AST) -> tuple[str, ...]:
        found = {model_of(inner) for node in nodes for inner in ast.walk(node)}
        return tuple(sorted(name for name in found if name))

    def chain_models(node: ast.AST) -> tuple[str, ...]:
        """The models named by the `select(...)` at the start of a method chain."""
        while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            node = node.func.value
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "select"
        ):
            return models_in(*node.args)
        return ()

    def exempt(line: int) -> bool:
        """The comment is on the query's own line, or alone on the line above."""
        if EXEMPT.search(lines[line - 1]):
            return True
        above = lines[line - 2].strip() if line >= 2 else ""
        return above.startswith("#") and bool(EXEMPT.search(above))

    found: list[tuple[tuple[int, int, int], Finding]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kind, names = None, ()
        function = node.func
        if isinstance(function, ast.Name) and function.id in STATEMENTS:
            kind, names = (
                function.id,
                models_in(*node.args, *(k.value for k in node.keywords)),
            )
        elif isinstance(function, ast.Attribute):
            if (
                function.attr in STATEMENTS
                and isinstance(function.value, ast.Name)
                and function.value.id in {"sa", "sqlalchemy"}
            ):
                kind, names = (
                    function.attr,
                    models_in(*node.args, *(k.value for k in node.keywords)),
                )
            elif function.attr == "get" and node.args:
                kind, names = (
                    "get",
                    models_in(node.args[0]) if model_of(node.args[0]) else (),
                )
            elif function.attr == "query":
                kind, names = "query", models_in(*node.args)
            elif function.attr in JOINS and node.args:
                kind, names = (
                    "join",
                    models_in(node.args[0]) if model_of(node.args[0]) else (),
                )
            elif function.attr == SELECT_FROM and node.args:
                kind = SELECT_FROM
                names = tuple(
                    sorted(
                        set(models_in(*node.args)) - set(chain_models(function.value))
                    )
                )
        if kind and names and not exempt(node.lineno):
            found.append(
                (
                    (node.lineno, node.col_offset, ORDER[kind]),
                    Finding(node.lineno, kind, names),
                )
            )
    return [finding for _, finding in sorted(found, key=lambda item: item[0])]


def scan_files() -> dict[str, list[Finding]]:
    """Findings per file under api/app, leaving out app/tenancy/ where the helpers live."""
    tenant = tenant_class_names()
    result: dict[str, list[Finding]] = {}
    for path in sorted(APP.rglob("*.py")):
        relative = path.relative_to(REPO).as_posix()
        if "/tenancy/" in relative:
            continue
        findings = scan_source(path.read_text(encoding="utf-8"), tenant)
        if findings:
            result[relative] = findings
    return result


def scan_app() -> dict[str, int]:
    return {path: len(findings) for path, findings in scan_files().items()}


def load_baseline() -> dict[str, int]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))["files"]


def write_baseline() -> dict[str, int]:
    files = scan_app()
    BASELINE_PATH.write_text(
        json.dumps({"total": sum(files.values()), "files": files}, indent=2) + "\n",
        encoding="utf-8",
    )
    return files


def report() -> str:
    lines = []
    for path, findings in scan_files().items():
        lines.append(f"{path}: {len(findings)}")
        for finding in findings:
            lines.append(
                f"    line {finding.line}: {finding.kind} {', '.join(finding.models)}"
            )
    return "\n".join(lines)


if __name__ == "__main__":
    if "--update" in sys.argv:
        files = write_baseline()
        print(f"Baseline written: {sum(files.values())} queries in {len(files)} files.")
    else:
        print(report())

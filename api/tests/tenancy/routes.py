"""The route list, read from the running app, and a way to call any route with chosen ids.

Nothing here is a hand-kept list of routes. The routes come from the app's OpenAPI
schema, and a request for each is built from that schema, so a new route is covered as
soon as it exists. A route whose request can't be built from the schema fails loudly
instead of being skipped. The few bodies the schema can't describe are in BODIES.
"""

from __future__ import annotations

import hashlib
import importlib
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

METHODS = ("get", "post", "put", "patch", "delete")
PATH_PARAM = re.compile(r"{([^}]+)}")

# Not tenant data: liveness checks and sign in.
EXEMPT_PATHS = frozenset({"/health", "/engine/health"})
EXEMPT_PREFIXES = ("/auth",)
# The block that makes each router org-aware (docs/multitenancy.md).
BLOCK_BY_PREFIX = {
    "/admin": 3,
    "/content": 3,
    "/insights": 3,
    "/workflow": 3,
    "/engine": 4,
    "/gateway": 4,
    "/governance": 4,
    "/memory": 4,
}


# These routers decide at import time whether to mount the real service or its mock.
FLAG_ROUTERS = (
    "app.clients.router",
    "app.engine.router",
    "app.gateway.router",
    "app.governance.router",
    "app.memory.router",
)


@contextmanager
def real_services() -> Iterator[None]:
    """Mounts the real engine, gateway, memory and governance routes, then puts the mocks back."""
    with pytest.MonkeyPatch.context() as patch:
        for service in ("ENGINE", "GATEWAY", "MEMORY"):
            patch.setenv(f"USE_MOCK_{service}", "false")
        for name in FLAG_ROUTERS:
            importlib.reload(importlib.import_module(name))
        yield
    for name in FLAG_ROUTERS:
        importlib.reload(importlib.import_module(name))


@dataclass(frozen=True)
class Route:
    method: str
    path: str

    @property
    def name(self) -> str:
        return f"{self.method} {self.path}"

    @property
    def prefix(self) -> str:
        return "/" + self.path.split("/")[1]

    @property
    def block(self) -> int | None:
        """The block that isolates this route, or None for a route with no tenant data."""
        if self.path in EXEMPT_PATHS or self.prefix in EXEMPT_PREFIXES:
            return None
        return BLOCK_BY_PREFIX.get(self.prefix, -1)


def route_table(app: FastAPI) -> list[Route]:
    """Every method and path the app serves, except its own docs."""
    paths = app.openapi()["paths"]
    return sorted(
        (
            Route(method.upper(), path)
            for path, item in paths.items()
            for method in item
            if method in METHODS
        ),
        key=lambda route: (route.path, route.method),
    )


@lru_cache(maxsize=1)
def real_routes() -> tuple[dict, list[Route]]:
    """The OpenAPI schema and route list of the app with every real service mounted."""
    from app.main import create_app

    with real_services():
        application = create_app()
        return application.openapi(), route_table(application)


def normal_path(path: str) -> str:
    """`/engine/reviews/{id}/findings` and `/engine/reviews/{review_id}/findings` match."""
    return PATH_PARAM.sub("{}", path)


def fake_ids(ids: dict) -> dict:
    """The same names with ids that exist nowhere, to see what a missing row looks like."""
    return {
        name: [f"nowhere-{name}-{uuid.uuid4().hex[:8]}"]
        if isinstance(value, list)
        else f"nowhere-{name}-{uuid.uuid4().hex[:8]}"
        for name, value in ids.items()
    }


def _flatten(ids: dict) -> list[str]:
    flat: list[str] = []
    for value in ids.values():
        flat.extend(value if isinstance(value, list) else [value])
    return flat


# Bodies the schema can't describe well enough. Each takes the ids to put in and the text
# to write, so what a caller creates can be found again in the other org's reads.
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def colour_for(text: str) -> str:
    """A hex colour that identifies one test's write, for the routes that only take colours."""
    return "#" + hashlib.sha1(text.encode()).hexdigest()[:6].upper()


def write_needles(text: str) -> list[str]:
    """Everything that would show a write made with this text, wherever it ended up."""
    return [text, colour_for(text)]


def _gaps(ids: dict, text: str) -> list[dict]:
    return [
        {
            "id": f"gap-{uuid.uuid4().hex[:8]}",
            "review_id": ids["review_id"],
            "check": "tone",
            "text": text,
            "explanation": "None",
            "created_at": "2026-01-01T00:00:00Z",
        }
    ]


BODIES: dict[tuple[str, str], Any] = {
    ("POST", "/auth/login"): lambda ids, text: {
        "json": {"email": "nobody@tenancy.test", "password": "not-a-password"},
    },
    ("POST", "/content"): lambda ids, text: {
        "form": {
            "title": text,
            "channel": "blog",
            "source": "in-house",
            "data_class": "public",
            "text": text,
        },
    },
    ("POST", "/content/{content_id}/versions"): lambda ids, text: {
        "form": {"text": text}
    },
    ("POST", "/admin/ingest"): lambda ids, text: {
        "files": {
            "file": ("guide.txt", f"2. Voice\n2.1   {text}\n".encode(), "text/plain")
        },
    },
    ("POST", "/admin/assets"): lambda ids, text: {
        "form": {"kind": "logo"},
        "files": {"file": (f"{text}.png", PNG, "image/png")},
    },
    ("POST", "/admin/assets/palette"): lambda ids, text: {
        "json": {"colours": [colour_for(text)]},
    },
    ("POST", "/admin/gaps"): lambda ids, text: {
        "json": _gaps(ids, text),
        "uses_ids": True,
    },
    ("POST", "/engine/eval/gate"): lambda ids, text: {
        "json": {
            "id": "p-test",
            "rule_id": ids["approved_rule_id"],
            "kind": "amendment",
            "current": "a",
            "suggested": text,
            "evidence": {"count": 3, "examples": []},
            "status": "pending",
        },
        "uses_ids": True,
    },
}

# Read routes that admins can't use. Everything else is read as the org's admin.
READ_AS = {"/workflow/queue": "reviewer"}


class Unbuildable(AssertionError):
    """A request for this route can't be built from its schema. Add it to BODIES."""


def _resolve(spec: dict, schema: dict) -> dict:
    while "$ref" in schema:
        schema = spec["components"]["schemas"][schema["$ref"].split("/")[-1]]
    return schema


def _value(
    spec: dict, schema: dict, name: str, ids: dict, used: list, text: str
) -> Any:
    """A minimal valid value for one field, using a real or made-up id where one fits."""
    if name in ids:
        used.append(name)
        return ids[name]
    schema = _resolve(spec, schema)
    if "anyOf" in schema:
        options = [option for option in schema["anyOf"] if option.get("type") != "null"]
        return _value(spec, options[0], name, ids, used, text)
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "string":
        return text
    if kind == "integer":
        return 1
    if kind == "number":
        return 0.5
    if kind == "boolean":
        return False
    if kind == "array":
        return []
    if kind == "object":
        required = schema.get("required", [])
        return {
            field: _value(spec, schema["properties"][field], field, ids, used, text)
            for field in required
        }
    raise Unbuildable(f"no value for field {name!r} with schema {schema}")


def build_request(spec: dict, route: Route, ids: dict, text: str = "x") -> dict:
    """Keyword arguments for TestClient.request, plus whether any id was used."""
    operation = spec["paths"][route.path][route.method.lower()]
    used: list[str] = []
    path = route.path
    params: dict[str, str] = {}
    for parameter in operation.get("parameters", []):
        name, place = parameter["name"], parameter["in"]
        if place == "path":
            if name not in ids:
                raise Unbuildable(
                    f"{route.name}: no id known for the path parameter {name!r}"
                )
            used.append(name)
            path = path.replace("{" + name + "}", quote(str(ids[name]), safe=""))
        elif place == "query" and parameter.get("required"):
            if name not in ids:
                raise Unbuildable(
                    f"{route.name}: no id known for the query parameter {name!r}"
                )
            used.append(name)
            params[name] = str(ids[name])

    request: dict[str, Any] = {"url": path, "params": params}
    override = BODIES.get((route.method, route.path))
    if override is not None:
        built = override(ids, text)
        request.update({key: built[key] for key in ("json", "files") if key in built})
        if "form" in built:
            request["data"] = built["form"]
        if built.get("uses_ids") or any(name in str(built) for name in _flatten(ids)):
            used.append("body")
    elif "requestBody" in operation:
        content = operation["requestBody"]["content"]
        if "application/json" in content:
            request["json"] = _value(
                spec, content["application/json"]["schema"], "body", ids, used, text
            )
        else:
            raise Unbuildable(
                f"{route.name}: a {list(content)} body needs an entry in BODIES"
            )
    request["_uses_ids"] = bool(used)
    return request


def call(client: TestClient, spec: dict, route: Route, ids: dict, text: str = "x"):
    """Calls a route with the given ids. Returns the response and whether ids were used."""
    request = build_request(spec, route, ids, text)
    uses_ids = request.pop("_uses_ids")
    url = request.pop("url")
    response = client.request(route.method, url, **request)
    return response, uses_ids

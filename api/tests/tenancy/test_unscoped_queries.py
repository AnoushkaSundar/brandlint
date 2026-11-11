"""CI check: tenant tables are queried only through the scoped helpers.

The scanner reads every file under api/app (except app/tenancy/, where the helpers live)
and finds each place a tenant model is queried without a helper: `session.get(Model, ...)`,
`select/update/delete(Model...)`, `session.query(Model)` and a `.join(Model, ...)`.

Block 2 only adds the helpers, so the queries that exist today are recorded in
unscoped_baseline.json, by file. The check fails if a file gains a query, so no new
unscoped query can be added, and it fails if a file loses one without the baseline being
updated, so Blocks 3 and 4 can only move the numbers down. Run
`python -m tests.tenancy.queries --update` from api/ to rewrite the baseline.

A query that is correct without a scope, such as looking a user up by email to find out
which org they belong to, carries `# unscoped-ok: <reason>` on its line or the line above.
"""

from __future__ import annotations

import textwrap

import pytest

from tests.tenancy import queries

TENANT = {"Content", "Edge", "Review", "Finding", "Rule", "User"}


def found(source: str, tenant: set[str] = TENANT) -> list[tuple[str, tuple[str, ...]]]:
    return [
        (f.kind, f.models) for f in queries.scan_source(textwrap.dedent(source), tenant)
    ]


# What the scanner recognises


def test_a_plain_get_is_flagged():
    source = """
        from app.content.models import Content
        def f(session, cid):
            return session.get(Content, cid)
    """
    assert found(source) == [("get", ("Content",))]


@pytest.mark.parametrize(
    "statement",
    [
        "select(Content)",
        "select(Content.id)",
        "select(Content.id, Content.title).where(Content.state == 'x')",
        "select(func.count(Content.id))",
        "select(func.count(func.distinct(Content.id)))",
    ],
)
def test_a_select_of_a_tenant_model_is_flagged(statement):
    source = f"""
        from app.content.models import Content
        def f(session):
            return session.scalars({statement})
    """
    assert found(source) == [("select", ("Content",))]


def test_update_and_delete_are_flagged():
    source = """
        from app.content.models import Content
        def f(session):
            session.execute(update(Content).values(state='x'))
            session.execute(delete(Content))
    """
    assert found(source) == [("update", ("Content",)), ("delete", ("Content",))]


def test_a_select_of_several_tenant_models_is_one_finding():
    source = """
        from app.memory.models import Edge
        from app.content.models import Content
        def f(session):
            return session.execute(select(Edge, Content.state))
    """
    assert found(source) == [("select", ("Content", "Edge"))]


def test_a_join_of_a_tenant_model_is_flagged():
    source = """
        from app.content.models import Content
        from app.workflow.models import Review
        def f(session):
            return session.scalars(select(Content).join(Review, Review.id == Content.id))
    """
    assert found(source) == [("select", ("Content",)), ("join", ("Review",))]


def test_a_select_from_a_tenant_model_is_flagged_when_the_select_names_none():
    source = """
        from app.content.models import Content
        def f(session):
            return session.scalar(select(func.count()).select_from(Content))
    """
    assert found(source) == [("select_from", ("Content",))]


def test_a_select_from_is_not_counted_twice_with_its_select():
    source = """
        from app.content.models import Content
        def f(session):
            return session.scalar(select(Content.id).select_from(Content))
    """
    assert found(source) == [("select", ("Content",))]


def test_a_legacy_query_call_is_flagged():
    source = """
        from app.content.models import Content
        def f(session):
            return session.query(Content).all()
    """
    assert found(source) == [("query", ("Content",))]


def test_an_import_alias_is_followed():
    source = """
        from app.admin.models import Rule as RuleRow
        def f(session):
            return session.scalars(select(RuleRow))
    """
    assert found(source) == [("select", ("Rule",))]


def test_a_model_reached_through_its_module_is_followed():
    source = """
        from app.engine import models
        import app.admin.models as admin_models
        def f(session):
            session.scalars(select(models.Finding))
            session.scalars(select(admin_models.Rule))
    """
    assert found(source) == [("select", ("Finding",)), ("select", ("Rule",))]


def test_a_relative_import_of_a_model_is_followed():
    source = """
        from .models import Content
        def f(session):
            return session.get(Content, 1)
    """
    assert found(source) == [("get", ("Content",))]


# What it leaves alone


def test_a_contract_with_the_same_name_as_a_model_is_not_a_model():
    source = """
        from app.contracts import Rule
        def f(rules):
            return select(Rule), rules.get(Rule)
    """
    assert found(source) == []


def test_the_scoped_helpers_are_not_flagged():
    source = """
        from app.content.models import Content
        from app.tenancy import scoped, scoped_get
        def f(session, cid):
            scoped_get(session, Content, cid)
            return session.scalars(scoped(session, Content).where(Content.state == 'x'))
    """
    assert found(source) == []


def test_models_that_are_not_tenant_data_are_not_flagged():
    source = """
        from app.auth.models import Organization
        def f(session):
            return session.scalars(select(Organization))
    """
    assert found(source) == []


def test_a_get_on_something_else_is_not_flagged():
    source = """
        def f(cache, key):
            return cache.get(key), {}.get("Content")
    """
    assert found(source) == []


def test_an_unscoped_ok_comment_on_the_line_or_the_line_above_allows_a_query():
    source = """
        from app.auth.models import User
        def f(session, email, uid):
            # unscoped-ok: the user's org is what this finds out
            a = session.scalar(select(User).where(User.email == email))
            b = session.get(User, uid)  # unscoped-ok: the same
            c = session.get(User, uid)
            return a, b, c
    """
    assert found(source) == [("get", ("User",))]


def test_a_comment_without_a_reason_is_not_an_exemption():
    source = """
        from app.auth.models import User
        def f(session, uid):
            return session.get(User, uid)  # unscoped-ok:
    """
    assert found(source) == [("get", ("User",))]


# The app itself


def test_the_app_has_no_unscoped_queries_beyond_the_baseline():
    now = queries.scan_app()
    baseline = queries.load_baseline()

    added = {path: n for path, n in now.items() if n > baseline.get(path, 0)}
    assert not added, (
        "These files gained queries that don't go through app.tenancy "
        f"(scoped, scoped_get, scoped_join, scoped_update or scoped_delete): {added}. "
        "Use a helper, or add `# unscoped-ok: <reason>` if the query is right without a scope."
    )


def test_the_baseline_is_up_to_date():
    now = queries.scan_app()
    baseline = queries.load_baseline()

    moved = {
        path: (baseline.get(path, 0), now.get(path, 0))
        for path in baseline.keys() | now.keys()
        if baseline.get(path, 0) != now.get(path, 0)
    }
    assert not moved, (
        f"Queries were converted, so lower the baseline (was, now): {moved}. "
        "Run `python -m tests.tenancy.queries --update` from api/."
    )


def test_the_tenancy_package_is_not_scanned():
    assert not [path for path in queries.scan_app() if "/tenancy/" in path]


def test_every_baseline_entry_is_a_real_file():
    for path in queries.load_baseline():
        assert (queries.REPO / path).is_file(), path


def test_the_tenant_models_are_read_from_the_app():
    names = queries.tenant_class_names()

    assert {"Content", "Finding", "Rule", "User", "Edge", "Review"} <= names
    assert "Organization" not in names

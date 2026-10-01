"""Integration tests: run against the paired Lakebase branch via DATABASE_URL.

Skipped automatically when DATABASE_URL is not set (so unit runs stay offline). CI sets it from
`ci/lakebase.sh wait-and-export` to point at the ephemeral ci-pr-* branch, never a shared branch.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"),
                                reason="DATABASE_URL not set; integration test needs a branch")


@pytest.fixture()
def conn():
    import psycopg
    c = psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=60)
    yield c
    c.close()


def test_core_tables_present(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('app.users'), to_regclass('app.schema_migrations')")
        users, hist = cur.fetchone()
    assert users is not None, "app.users missing — migrations not applied?"
    assert hist is not None, "app.schema_migrations missing"


def test_migration_history_is_recorded(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM app.schema_migrations")
        assert cur.fetchone()[0] >= 1

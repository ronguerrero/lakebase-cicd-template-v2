#!/usr/bin/env python3
"""PostgreSQL migration runner — the procedural half of the CI/CD.

IN PLAIN TERMS: applies the ordered db/migrations/*.sql files to ONE database and records which
ones ran (version + checksum + git SHA). This is what moves V004 into app_dev_db, then app_qa_db,
then app_prod_db — the same files replayed against each database, which is the whole promotion.

Owns Postgres execution ONLY. Branch creation, endpoint discovery, and connection-ref
provisioning belong to ci/lakebase.sh (ci/lakebase_api.py); bundle deployment belongs to the
Databricks bundle workflow. Promotion = replaying this ordered migration set against each
target branch/database — never merging or copying a Lakebase branch.

The runner (runbook, section 10):
  * acquires a database-side advisory lock so two clients can't migrate at once
  * records applied versions + checksums; FAILS on a checksum change to an applied migration
  * applies pending migrations in deterministic order, each recorded with git sha + artifact sha
  * is safe to run repeatedly; supports a --validate dry run

Connection (either form):
  DATABASE_URL   a postgres URL for the branch (CI path; set by `ci/lakebase.sh wait-and-export`,
                 kept in the process env, never on the command line or in a log)
  --profile/--project/--branch/--database                                    (local/console path;
      mints a short-lived credential via the SDK and connects directly)
"""
import argparse
import glob
import hashlib
import os
import sys

LOCK_KEY = "lakebase_app_migrations"


def _repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here)


def _connect(a):
    import psycopg
    url = os.environ.get("DATABASE_URL")
    if url:
        return psycopg.connect(url, connect_timeout=60)
    # Local / console path: use the SDK engine to mint a credential and connect.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from lakebase_api import client, connect  # noqa: E402
    if not (a.project and a.branch and a.database):
        sys.exit("set DATABASE_URL, or pass --project/--branch/--database")
    return connect(client(a.profile), a.project, a.branch, a.database)


def _checksum(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def discover(directory):
    out = []
    for path in sorted(glob.glob(os.path.join(directory, "V*.sql"))):
        base = os.path.basename(path)
        ver = base.split("__", 1)[0]              # V001
        out.append((ver, base, path))
    return out


def ensure_history(cur):
    cur.execute("""
        CREATE SCHEMA IF NOT EXISTS app;
        CREATE TABLE IF NOT EXISTS app.schema_migrations (
            version         TEXT PRIMARY KEY,
            filename        TEXT NOT NULL,
            checksum        TEXT NOT NULL,
            git_sha         TEXT,
            artifact_sha256 TEXT,
            applied_by      TEXT NOT NULL DEFAULT current_user,
            applied_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );""")


def applied_map(cur):
    cur.execute("SELECT version, checksum FROM app.schema_migrations")
    return {v: c for v, c in cur.fetchall()}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--directory", default=os.path.join(_repo_root(), "db", "migrations"))
    p.add_argument("--validate", action="store_true", help="dry run: report applied/pending, apply nothing")
    p.add_argument("--to", default="", help="apply only up through this version inclusive (e.g. V003)")
    p.add_argument("--app-role", default=os.environ.get("APP_ROLE", ""),
                   help="PG role substituted for ${APP_ROLE} in grants (default: connecting role)")
    # direct-connection fallback (when DATABASE_URL is not set)
    p.add_argument("--profile", default=None)
    p.add_argument("--project", default=os.environ.get("LAKEBASE_PROJECT", "").split("/")[-1] or None)
    p.add_argument("--branch", default=os.environ.get("LAKEBASE_BRANCH"))
    p.add_argument("--database", default=os.environ.get("LAKEBASE_DATABASE"))
    a = p.parse_args()

    git_sha = os.environ.get("MIGRATION_GIT_SHA", "")
    artifact_sha = os.environ.get("ARTIFACT_SHA256", "")
    migrations = discover(a.directory)

    conn = _connect(a)
    try:
        with conn.cursor() as cur:
            ensure_history(cur)
        conn.commit()

        app_role = a.app_role
        if not app_role:
            with conn.cursor() as cur:
                cur.execute("SELECT current_user")
                app_role = cur.fetchone()[0]

        with conn.cursor() as cur:
            done = applied_map(cur)

        pending = []
        for ver, base, path in migrations:
            cs = _checksum(path)
            if ver in done:
                if done[ver] != cs:
                    sys.exit(f"ERROR: {base} changed after being applied (checksum drift). "
                             f"Never edit an applied migration — add a new one.")
            elif not a.to or ver <= a.to:
                pending.append((ver, base, path, cs))

        if a.validate:
            print(f"  validate: {len(done)} applied, {len(pending)} pending")
            for ver, base, *_ in pending:
                print(f"    pending {base}")
            return

        if not pending:
            print("  = up to date (nothing to apply)")
            return

        # One locked transaction: serialize against any other migration client.
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (LOCK_KEY,))
            for ver, base, path, cs in pending:
                with open(path, encoding="utf-8") as f:
                    sql = f.read().replace("${APP_ROLE}", app_role)
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO app.schema_migrations"
                    "(version, filename, checksum, git_sha, artifact_sha256) "
                    "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (version) DO NOTHING",
                    (ver, base, cs, git_sha, artifact_sha))
        conn.commit()
        for ver, base, *_ in pending:
            print(f"  + applied {base}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

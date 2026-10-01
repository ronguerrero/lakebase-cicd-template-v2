#!/usr/bin/env python3
"""Apply non-production seed data to a branch (runbook: seeds are validation-only, never promoted).

Runs every db/seeds/*.sql in order against the selected database. Connects via DATABASE_URL or,
for local/console use, via --profile/--project/--branch/--database (SDK credential).
"""
import argparse
import glob
import os
import sys


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _connect(a):
    import psycopg
    url = os.environ.get("DATABASE_URL")
    if url:
        return psycopg.connect(url, connect_timeout=60)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from lakebase_api import client, connect  # noqa: E402
    if not (a.project and a.branch and a.database):
        sys.exit("set DATABASE_URL, or pass --project/--branch/--database")
    return connect(client(a.profile), a.project, a.branch, a.database)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--directory", default=os.path.join(_repo_root(), "db", "seeds"))
    p.add_argument("--profile", default=None)
    p.add_argument("--project", default=None)
    p.add_argument("--branch", default=None)
    p.add_argument("--database", default=None)
    a = p.parse_args()

    files = sorted(glob.glob(os.path.join(a.directory, "*.sql")))
    conn = _connect(a)
    try:
        with conn.cursor() as cur:
            for f in files:
                with open(f, encoding="utf-8") as fh:
                    cur.execute(fh.read())
                print(f"  + seeded {os.path.basename(f)}")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()

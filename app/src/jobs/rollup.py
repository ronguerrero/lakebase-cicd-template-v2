"""Illustrative application job: a nightly rollup of users by signup source.

Deployed by the bundle (resources/jobs.yml), bound to the same Lakebase branch/database as the
app. Stands in for ordinary application workloads; it is NOT how migrations run (those run from
the CI runner — see ci/migrate.sh). Serverless spark_python_task does not define __file__, so
this script keeps its imports self-contained.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0] or "."))))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--connection-ref", default="")
    p.add_argument("--database", default=os.environ.get("LAKEBASE_DATABASE", "app_qa_db"))
    p.parse_args()

    from db import get_connection  # noqa: E402  (same src/ dir in the deployed app)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='app' "
                        "AND table_name='users' AND column_name='signup_source'")
            if not cur.fetchone():
                print("signup_source not present yet; nothing to roll up")
                return
            cur.execute("SELECT coalesce(signup_source,'unknown'), count(*) "
                        "FROM app.users GROUP BY 1 ORDER BY 2 DESC")
            for src, n in cur.fetchall():
                print(f"  {src}: {n}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

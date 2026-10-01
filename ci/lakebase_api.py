#!/usr/bin/env python3
"""Lakebase control-plane engine — the single place that knows how to talk to Lakebase.

`ci/lakebase.sh` shells into this; the guided console imports it. Centralizing the API here
is deliberate (see the runbook, section 7.1): CLI-version differences, readiness polling,
connection discovery, retries, reset, and cleanup live in one tested module instead of being
scattered across workflow files.

Verified against databricks-sdk >= 0.118.0 (the projects/branches "spec/status" model, tested
live at 0.139.0): a branch's endpoint detail reads back under `ep.status` (e.g.
`ep.status.hosts.host`), and a short-lived Postgres credential is minted with
`w.postgres.generate_database_credential(endpoint=ep.name)`.

Topology this engine assumes (one workspace, ONE long-lived branch, databases per environment):

    project <app-project>
      └── production   (the only long-lived branch; hosts all three databases)
            ├── app_dev_db      DEV baseline + DEV/PR source database
            ├── app_qa_db       QA application database
            ├── app_prod_db     PROD application database
            │
            ├── ci-pr-<n>            (ephemeral child of production; selects app_dev_db)
            ├── dev-<who>-<desc>     (ephemeral child of production; selects app_dev_db)
            ├── qa-preflight-<sha>   (ephemeral child of production; selects app_qa_db)
            └── prod-preflight-<sha> (ephemeral child of production; selects app_prod_db)

There is no long-lived dev or qa branch. Ephemeral branches are copy-on-write children of
production (they contain all three databases, but a workflow selects exactly one) and are never
promoted — only migrations move forward, replayed into app_dev_db, then app_qa_db, then app_prod_db.
"""
import argparse
import json
import sys
import time
import urllib.parse

# The default database every Lakebase branch is born with. We create the named
# per-environment databases (app_qa_db / app_prod_db) *inside* it.
BOOTSTRAP_DB = "databricks_postgres"


def client(profile=None):
    from databricks.sdk import WorkspaceClient
    return WorkspaceClient(profile=profile) if profile else WorkspaceClient()


# --------------------------------------------------------------------------- projects
def ensure_project(w, project, pg_version=16, max_cu=4):
    """Create the Lakebase project if missing. The project is born with a default branch
    named `production`; we add `qa` separately. Idempotent."""
    from databricks.sdk.service.postgres import (
        Project, ProjectSpec, ProjectDefaultEndpointSettings)
    try:
        w.postgres.get_project(name=f"projects/{project}")
        print(f"  = project exists: {project}")
        return
    except Exception:
        pass
    print(f"  + creating project {project} (pg {pg_version}, endpoints autoscale 1->{max_cu} CU) ...")
    w.postgres.create_project(
        project=Project(spec=ProjectSpec(
            display_name=project,
            pg_version=int(pg_version),
            default_endpoint_settings=ProjectDefaultEndpointSettings(
                autoscaling_limit_min_cu=1, autoscaling_limit_max_cu=max_cu))),
        project_id=project).wait()
    print(f"  + project created: {project}")


# --------------------------------------------------------------------------- branches
def list_branches(w, project):
    out = []
    for b in w.postgres.list_branches(parent=f"projects/{project}"):
        name = b.name.split("/")[-1]
        source = None
        state = None
        try:
            source = (b.spec.source_branch or "").split("/")[-1] or None
        except Exception:
            pass
        try:
            state = str(b.status.current_state) if b.status else None
        except Exception:
            pass
        out.append({"branch": name, "source": source, "state": state})
    return out


def ensure_branch(w, project, branch, source="production", no_expiry=False,
                  ttl_seconds=None, max_cu=4):
    """Create a copy-on-write branch off `source` and ensure it has a read/write endpoint.
    `no_expiry=True` for the long-lived production branch; `ttl_seconds` for ephemeral CI branches."""
    from databricks.sdk.service.postgres import (
        Branch, BranchSpec, Endpoint, EndpointSpec, EndpointType)
    full = f"projects/{project}/branches/{branch}"
    try:
        w.postgres.get_branch(name=full)
        print(f"  = branch exists: {branch}")
    except Exception:
        spec = BranchSpec(source_branch=f"projects/{project}/branches/{source}")
        if no_expiry:
            spec.no_expiry = True
        elif ttl_seconds:
            # spec.ttl is a protobuf Duration (serialized to e.g. "14400s" on the wire)
            from google.protobuf.duration_pb2 import Duration
            spec.ttl = Duration(seconds=int(ttl_seconds))
        print(f"  + creating branch {branch} off {source}"
              + (" (no expiry)" if no_expiry else f" (ttl {ttl_seconds}s)" if ttl_seconds else "")
              + " ...")
        w.postgres.create_branch(parent=f"projects/{project}",
                                 branch=Branch(spec=spec), branch_id=branch).wait()
        print(f"  + branch created: {branch}")
    _ensure_endpoint(w, full, branch, max_cu)


def _ensure_endpoint(w, full, branch, max_cu):
    from databricks.sdk.service.postgres import (
        Endpoint, EndpointSpec, EndpointType)
    try:
        eps = list(w.postgres.list_endpoints(parent=full))
    except Exception:
        eps = []
    if not eps:
        w.postgres.create_endpoint(
            parent=full,
            endpoint=Endpoint(spec=EndpointSpec(
                endpoint_type=EndpointType.ENDPOINT_TYPE_READ_WRITE,
                autoscaling_limit_min_cu=1, autoscaling_limit_max_cu=max_cu)),
            endpoint_id="primary").wait()
        print(f"  + endpoint created on {branch}")


def delete_branch(w, project, branch):
    """Idempotent: deleting an already-gone branch must not fail the workflow."""
    full = f"projects/{project}/branches/{branch}"
    try:
        w.postgres.delete_branch(name=full)
        print(f"  - deleted branch: {branch}")
    except Exception as e:  # noqa: BLE001
        print(f"  . no branch to delete: {branch} ({str(e)[:70]})")


# --------------------------------------------------------------------------- endpoints
def get_endpoint(w, project, branch, wait_provisioning=False, timeout=420, delay=6):
    """Return the branch's first endpoint. Lakebase endpoints scale to zero and WAKE ON
    CONNECT, so we never gate on a "ready" state (that blocks forever on a suspended
    endpoint) — we return the endpoint and let psycopg wake it. `wait_provisioning=True`
    waits only for the endpoint object to *exist*, right after creating a branch."""
    parent = f"projects/{project}/branches/{branch}"
    deadline = time.time() + timeout
    while True:
        eps = list(w.postgres.list_endpoints(parent=parent))
        if eps:
            return w.postgres.get_endpoint(name=eps[0].name)
        if not wait_provisioning or time.time() > deadline:
            raise RuntimeError(f"no endpoint on {parent}")
        time.sleep(delay)


# --------------------------------------------------------------------------- connections
def connect(w, project, branch, database, user=None, retries=6):
    """Open a psycopg connection to `database` on `branch`, tolerating scale-to-zero wake
    latency (~20-60s) by retrying with a freshly minted credential each attempt."""
    import psycopg
    ep = get_endpoint(w, project, branch)
    host = ep.status.hosts.host
    user = user or w.current_user.me().user_name
    last = None
    for _ in range(max(1, retries)):
        cred = w.postgres.generate_database_credential(endpoint=ep.name)
        try:
            return psycopg.connect(host=host, dbname=database, user=user,
                                   password=cred.token, sslmode="require", connect_timeout=60)
        except psycopg.OperationalError as e:
            last = e
            time.sleep(4)
    raise last


def ensure_database(w, project, branch, database):
    """Create a named database (e.g. app_qa_db) on a branch if it does not exist.
    Connects to the branch's bootstrap database to run CREATE DATABASE (which cannot run
    inside a transaction block). Child branches inherit it by copy-on-write."""
    conn = connect(w, project, branch, BOOTSTRAP_DB)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
            if cur.fetchone():
                print(f"  = database exists: {database} (on {branch})")
                return
            cur.execute(f'CREATE DATABASE "{database}"')
            print(f"  + database created: {database} (on {branch})")
    finally:
        conn.close()


def database_url(w, project, branch, database, user=None):
    """Build a postgres URL with a freshly minted token as the password. The runbook keeps
    credential-bearing URLs out of command-line args and in the process environment only;
    lakebase.sh writes this to $GITHUB_ENV / the shell env, never echoes it to a log."""
    ep = get_endpoint(w, project, branch)
    host = ep.status.hosts.host
    user = user or w.current_user.me().user_name
    cred = w.postgres.generate_database_credential(endpoint=ep.name)
    pw = urllib.parse.quote(cred.token, safe="")
    u = urllib.parse.quote(user, safe="")
    return f"postgresql://{u}:{pw}@{host}:5432/{database}?sslmode=require"


# --------------------------------------------------------------------------- CLI
def _tree(w, project):
    rows = list_branches(w, project)
    order = {"production": 0}
    rows.sort(key=lambda r: (order.get(r["branch"], 1), r["branch"]))
    print(f"project: {project}")
    for r in rows:
        tag = ""
        if r["branch"] == "production":
            tag = "  [LONG-LIVED -> app_dev_db + app_qa_db + app_prod_db]"
        elif r["branch"].startswith(("ci-pr-", "dev-")):
            tag = "  [ephemeral child of production -> selects app_dev_db]"
        elif "qa-preflight" in r["branch"]:
            tag = "  [ephemeral rehearsal -> selects app_qa_db]"
        elif "prod-preflight" in r["branch"]:
            tag = "  [ephemeral rehearsal -> selects app_prod_db]"
        src = f" (off {r['source']})" if r["source"] else ""
        print(f"  - {r['branch']}{src}{tag}")


def main():
    p = argparse.ArgumentParser(description="Lakebase control-plane engine")
    p.add_argument("--profile", default=None, help="CLI profile; omit for ambient (in-job) auth")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init-project"); sp.add_argument("--project", required=True)
    sp.add_argument("--max-cu", type=int, default=4); sp.add_argument("--pg-version", type=int, default=16)

    sp = sub.add_parser("ensure-branch"); sp.add_argument("--project", required=True)
    sp.add_argument("--branch", required=True); sp.add_argument("--source", default="production")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--no-expiry", action="store_true"); g.add_argument("--ttl", type=int, default=None)

    sp = sub.add_parser("delete-branch"); sp.add_argument("--project", required=True)
    sp.add_argument("--branch", required=True)

    sp = sub.add_parser("ensure-database"); sp.add_argument("--project", required=True)
    sp.add_argument("--branch", required=True); sp.add_argument("--database", required=True)

    sp = sub.add_parser("wait-endpoint"); sp.add_argument("--project", required=True)
    sp.add_argument("--branch", required=True)

    sp = sub.add_parser("list-branches"); sp.add_argument("--project", required=True)
    sp = sub.add_parser("tree"); sp.add_argument("--project", required=True)

    sp = sub.add_parser("export-url"); sp.add_argument("--project", required=True)
    sp.add_argument("--branch", required=True); sp.add_argument("--database", required=True)
    sp.add_argument("--user", default=None)
    sp.add_argument("--var", default="LAKEBASE_DATABASE_URL", help="env var name to emit")

    a = p.parse_args()
    w = client(a.profile)

    if a.cmd == "init-project":
        ensure_project(w, a.project, pg_version=a.pg_version, max_cu=a.max_cu)
    elif a.cmd == "ensure-branch":
        ensure_branch(w, a.project, a.branch, source=a.source,
                      no_expiry=a.no_expiry, ttl_seconds=a.ttl)
    elif a.cmd == "delete-branch":
        delete_branch(w, a.project, a.branch)
    elif a.cmd == "ensure-database":
        ensure_database(w, a.project, a.branch, a.database)
    elif a.cmd == "wait-endpoint":
        ep = get_endpoint(w, a.project, a.branch, wait_provisioning=True)
        print(f"  = endpoint present on {a.branch}: {ep.status.hosts.host}")
    elif a.cmd == "list-branches":
        print(json.dumps(list_branches(w, a.project), indent=2))
    elif a.cmd == "tree":
        _tree(w, a.project)
    elif a.cmd == "export-url":
        # emit KEY=VALUE for `>> "$GITHUB_ENV"` / `eval`; never log the value elsewhere
        print(f'{a.var}={database_url(w, a.project, a.branch, a.database, a.user)}')


if __name__ == "__main__":
    main()

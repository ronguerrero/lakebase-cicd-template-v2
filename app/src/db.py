"""Runtime database access for the sample app.

Self-contained (the app ships without the ci/ helpers): it mints a short-lived Lakebase
credential with the Databricks SDK and connects with psycopg. In a deployed Databricks App auth
is ambient (the app's own service principal); locally it falls back to DATABRICKS_CONFIG_PROFILE.

The deployment tuple arrives as environment variables set by the bundle target:
    LAKEBASE_PROJECT / LAKEBASE_BRANCH / LAKEBASE_DATABASE
so the same code runs unchanged against ci-pr-*, qa, or production.
"""
import os
import time

BOOTSTRAP_DB = "databricks_postgres"


def _client():
    from databricks.sdk import WorkspaceClient
    profile = os.environ.get("DATABRICKS_CONFIG_PROFILE")
    return WorkspaceClient(profile=profile) if profile else WorkspaceClient()


def get_connection(retries=6):
    import psycopg
    w = _client()
    project = os.environ.get("LAKEBASE_PROJECT", "lakebase-app").split("/")[-1]
    branch = os.environ.get("LAKEBASE_BRANCH", "production")
    database = os.environ.get("LAKEBASE_DATABASE", BOOTSTRAP_DB)

    eps = list(w.postgres.list_endpoints(parent=f"projects/{project}/branches/{branch}"))
    if not eps:
        raise RuntimeError(f"no endpoint on projects/{project}/branches/{branch}")
    ep = w.postgres.get_endpoint(name=eps[0].name)
    host = ep.status.hosts.host
    user = w.current_user.me().user_name

    last = None
    for _ in range(retries):                       # endpoints scale to zero; wake on connect
        cred = w.postgres.generate_database_credential(endpoint=ep.name)
        try:
            return psycopg.connect(host=host, dbname=database, user=user,
                                   password=cred.token, sslmode="require", connect_timeout=60)
        except psycopg.OperationalError as e:
            last = e
            time.sleep(4)
    raise last

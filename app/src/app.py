"""Sample Lakebase app: a tiny user directory.

Shows what the app under promotion looks like at each environment — which Lakebase branch and
database it is bound to, the applied schema version, and the data it reads. It is deliberately
small; the point of the template is the lifecycle around it, not the app itself.
"""
import os
from flask import Flask, render_template_string

from db import get_connection

app = Flask(__name__)

PAGE = """<!doctype html><meta charset=utf-8>
<title>User Directory — {{ env }}</title>
<style>
  body{font-family:system-ui,sans-serif;margin:2rem;color:#1a2b3c}
  .env{display:inline-block;padding:.2rem .6rem;border-radius:999px;background:#e8f0fe;color:#1a56db;font-weight:600}
  table{border-collapse:collapse;margin-top:1rem}td,th{border:1px solid #d7dde5;padding:.4rem .8rem;text-align:left}
  .meta{color:#5a6b7c;margin-top:.5rem}
</style>
<h1>User Directory <span class=env>{{ env }}</span></h1>
<p class=meta>branch <b>{{ branch }}</b> &middot; database <b>{{ database }}</b> &middot; schema version <b>{{ version }}</b>
  &middot; signup_source column: <b>{{ has_source }}</b></p>
<table><tr><th>ID</th><th>Email</th><th>Name</th><th>Status</th>{% if has_source == 'present' %}<th>Signup source</th>{% endif %}</tr>
{% for u in users %}<tr><td>{{u[0]}}</td><td>{{u[1]}}</td><td>{{u[2]}}</td><td>{{u[3]}}</td>
{% if has_source == 'present' %}<td>{{u[4]}}</td>{% endif %}</tr>{% endfor %}
</table>"""


@app.get("/")
def index():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT coalesce(max(version),'(none)') FROM app.schema_migrations")
            version = cur.fetchone()[0]
            cur.execute("""SELECT 1 FROM information_schema.columns
                           WHERE table_schema='app' AND table_name='users'
                             AND column_name='signup_source'""")
            has_source = "present" if cur.fetchone() else "absent"
            cols = "user_id, email, display_name, status" + (", signup_source" if has_source == "present" else "")
            cur.execute(f"SELECT {cols} FROM app.users ORDER BY user_id")
            users = cur.fetchall()
    finally:
        conn.close()
    return render_template_string(
        PAGE, env=os.environ.get("APP_ENVIRONMENT", "local"),
        branch=os.environ.get("LAKEBASE_BRANCH", "?"),
        database=os.environ.get("LAKEBASE_DATABASE", "?"),
        version=version, has_source=has_source, users=users)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")))

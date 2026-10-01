#!/usr/bin/env python3
"""Guided Lakebase CI/CD console — single long-lived branch, databases per environment.

Walks the developer lifecycle for the revised runbook: ONE workspace, ONE Lakebase project, ONE
long-lived branch `production` that hosts three databases (app_dev_db / app_qa_db / app_prod_db).
There is no long-lived dev or qa branch. A change is promoted by REPLAYING the same migrations
into production/app_dev_db (the DEV baseline), then production/app_qa_db, then production/app_prod_db
after approval — same branch, different database selector each time.

For each stage it SHOWS the exact command and the underlying Lakebase API call, runs it live, and
updates the branch tree and the three per-database panels so the audience watches the change roll
dev -> qa -> prod across the databases on one branch.

Run:  python demo/console.py        (serves http://127.0.0.1:8052)
"""
import os
import subprocess
import sys
import threading
import time

import dash
from dash import Input, Output, dcc, html

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CI = os.path.join(REPO, "ci")
sys.path.insert(0, CI)
import lakebase_api as lb  # noqa: E402

# ----------------------------------------------------------------------------- config
PROFILE = os.environ.get("DEMO_PROFILE", "lakebase-dev")   # your single-workspace CLI profile
PROJECT = os.environ.get("DEMO_PROJECT", "lakebase-app")
BRANCH = "production"                                       # the only long-lived branch
DEV_DB, QA_DB, PROD_DB = "app_dev_db", "app_qa_db", "app_prod_db"
DEV_BRANCH = "dev-demo-signup-source"                      # ephemeral child, selects app_dev_db
PROD_PREFLIGHT = "prod-preflight-demo"                     # ephemeral child, selects app_prod_db
GIT_SHA = "demo-" + time.strftime("%Y%m%d")

MIG = os.path.join(CI, "migrate.py")
SEED = os.path.join(CI, "seed.py")
LKB = os.path.join(CI, "lakebase.sh")

# Run every subprocess with THIS interpreter (the venv that has the SDK/psycopg), and prepend its
# bin dir to PATH so the `python3` inside ci/*.sh resolves to the venv too — not system python.
PYBIN = sys.executable
VENV_BIN = os.path.dirname(PYBIN)

C = {"ink": "#0f2a3f", "mut": "#5a6b7c", "line": "#d7dde5", "bg": "#f5f7fa",
     "card": "#ffffff", "accent": "#1a56db", "accent2": "#e8f0fe",
     "ok": "#1e7a46", "run": "#b4690e", "err": "#b42318", "code": "#0b1f33"}


def _mig(branch, db, to=""):
    a = [PYBIN, MIG, "--profile", PROFILE, "--project", PROJECT, "--branch", branch, "--database", db]
    return a + (["--to", to] if to else [])


def _seed(branch, db):
    return [PYBIN, SEED, "--profile", PROFILE, "--project", PROJECT, "--branch", branch, "--database", db]


# stage: id, title, _, blurb, [(display_cmd, argv_or_None)...], api_note
STAGES = [
    ("setup", "0 · Platform setup + baseline", "",
     "One project, one long-lived branch `production` holding all three databases. Seed each of "
     "app_dev_db / app_qa_db / app_prod_db to the V003 baseline. V004 is the pending change this "
     "demo promotes across the three databases.",
     [("./ci/lakebase.sh init lakebase-app", ["bash", LKB, "init", PROJECT]),
      ("./ci/migrate.sh --branch production --database app_dev_db  --to V003", _mig(BRANCH, DEV_DB, "V003")),
      ("./ci/seed.py    --branch production --database app_dev_db", _seed(BRANCH, DEV_DB)),
      ("./ci/migrate.sh --branch production --database app_qa_db   --to V003", _mig(BRANCH, QA_DB, "V003")),
      ("./ci/seed.py    --branch production --database app_qa_db", _seed(BRANCH, QA_DB)),
      ("./ci/migrate.sh --branch production --database app_prod_db --to V003", _mig(BRANCH, PROD_DB, "V003")),
      ("./ci/seed.py    --branch production --database app_prod_db", _seed(BRANCH, PROD_DB))],
     "postgres.create_project · create_branch(production, no_expiry) · CREATE DATABASE x3"),

    ("feature", "1 · Start the change", "",
     "A Git feature branch for the code, plus a copy-on-write Lakebase branch cut from `production` "
     "that SELECTS app_dev_db. The child contains all three databases but the workflow uses only "
     "app_dev_db — it is a validation host, never promoted.",
     [("git switch -c feature/APP-204-signup-source", None),
      ("./ci/lakebase.sh prepare-ci-branch lakebase-app dev-demo-signup-source --source-branch production --database app_dev_db --reset-existing",
       ["bash", LKB, "prepare-ci-branch", PROJECT, DEV_BRANCH, "--source-branch", BRANCH,
        "--database", DEV_DB, "--reset-existing"])],
     "postgres.create_branch(spec.source_branch=projects/lakebase-app/branches/production) — copy-on-write"),

    ("migrate-branch", "2 · Apply the migration on the branch", "",
     "Apply the ordered migrations to the child's app_dev_db. V001–V003 are already present; only "
     "V004 is pending. The runner records version, checksum, git SHA, and refuses edits to an "
     "already-applied migration.",
     [("./ci/check_migrations.sh db/migrations",
       ["bash", os.path.join(CI, "check_migrations.sh"), os.path.join(REPO, "db", "migrations")]),
      ("./ci/migrate.sh --branch dev-demo-signup-source --database app_dev_db", _mig(DEV_BRANCH, DEV_DB))],
     "psycopg → pg_advisory_xact_lock → apply V004 → INSERT app.schema_migrations"),

    ("test-branch", "3 · Validate on the branch", "",
     "Unit tests (offline) and a validate pass against the child's app_dev_db confirm the migration "
     "applied and nothing is pending. In CI, integration + smoke tests and a cross-database denial "
     "check run here against the isolated branch.",
     [("pytest tests/unit app/tests", [PYBIN, "-m", "pytest", "-q",
                                        os.path.join(REPO, "tests", "unit"), os.path.join(REPO, "app", "tests")]),
      ("./ci/migrate.sh --branch dev-demo-signup-source --database app_dev_db --validate",
       _mig(DEV_BRANCH, DEV_DB) + ["--validate"])],
     "pytest · schema-diff · migrate --validate · permission-tests (deny app_dev_runtime→app_qa_db/app_prod_db)"),

    ("build", "4 · Merge → build once", "",
     "On merge to main the app is built exactly once and published with a SHA-256 digest. Every "
     "later database gets these same bytes, verified by digest — never a rebuild.",
     [("./ci/build.sh demo-sha", ["bash", os.path.join(CI, "build.sh"), GIT_SHA]),
      ("./ci/publish_artifact.sh --sha demo-sha",
       ["bash", os.path.join(CI, "publish_artifact.sh"), "--sha", GIT_SHA, "--output", "/dev/stdout"])],
     "deterministic tar + sha256 → immutable artifact URI"),

    ("dev-baseline", "5 · DEV baseline (NEW)", "",
     "Post-merge, replay the migration set into production/app_dev_db — the shared DEV baseline that "
     "every future feature branch is cut from. This is the new first promotion stop in the revised "
     "runbook; it keeps the DEV database current ahead of the team.",
     [("./ci/migrate.sh --branch production --database app_dev_db", _mig(BRANCH, DEV_DB))],
     "replay migrations into production/app_dev_db (dev-baseline CI job, sp-app-dev-cicd)"),

    ("deploy-qa", "6 · Deploy to QA", "",
     "Replay the SAME migration set into production/app_qa_db, then deploy the built artifact. Same "
     "branch as DEV — only the database selector changes. Promotion is a replay, not a branch copy. "
     "(A QA preflight branch is OPTIONAL in the runbook — used only for risky migrations — and is "
     "not part of this walkthrough; step 7's prod preflight shows the rehearsal-on-a-branch pattern.)",
     [("./ci/migrate.sh --branch production --database app_qa_db", _mig(BRANCH, QA_DB)),
      ("databricks bundle deploy --target qa --var=lakebase_branch=production --var=lakebase_database=app_qa_db", None)],
     "replay migrations into production/app_qa_db → bundle deploy --target qa (same artifact)"),

    ("prod-preflight", "7 · Production preflight", "",
     "Rehearse on a disposable child of `production` that SELECTS app_prod_db — proving the migration "
     "against production-shaped data without touching it — then destroy the rehearsal branch.",
     [("./ci/lakebase.sh create-preflight prod-preflight-demo lakebase-app --source-branch production",
       ["bash", LKB, "create-preflight", PROD_PREFLIGHT, PROJECT, "--source-branch", BRANCH]),
      ("./ci/migrate.sh --branch prod-preflight-demo --database app_prod_db", _mig(PROD_PREFLIGHT, PROD_DB)),
      ("./ci/lakebase.sh delete-ci-branch prod-preflight-demo lakebase-app",
       ["bash", LKB, "delete-ci-branch", PROD_PREFLIGHT, PROJECT])],
     "create_branch off production (selects app_prod_db) → rehearse → delete_branch"),

    ("deploy-prod", "8 · 🔒 Approve → deploy to PROD", "",
     "After the required approval, replay the SAME migration set into production/app_prod_db and "
     "deploy the SAME verified artifact. Only this step touches the production database.",
     [("./ci/migrate.sh --branch production --database app_prod_db", _mig(BRANCH, PROD_DB)),
      ("databricks bundle deploy --target prod --var=lakebase_branch=production --var=lakebase_database=app_prod_db", None),
      ("git tag -a release-demo-sha", None)],
     "replay migrations into production/app_prod_db → bundle deploy --target prod → tag release"),

    ("cleanup", "9 · Clean up", "",
     "Delete the ephemeral feature branch. Idempotent — a scheduled job sweeps any orphans by TTL. "
     "The stable `production` branch and its three databases remain.",
     [("./ci/lakebase.sh delete-ci-branch dev-demo-signup-source lakebase-app",
       ["bash", LKB, "delete-ci-branch", DEV_BRANCH, PROJECT])],
     "delete_branch (idempotent)"),
]
STAGE_IDS = [s[0] for s in STAGES]

# What each stage acts on — drives the per-card "acts on" line and the live topology diagram.
# keys reference diagram cells: dev/qa/prod = the three databases on production; devchild = the
# ephemeral dev/PR child; preflight = the ephemeral prod-preflight child.
ACTS = {
    "setup":          {"keys": {"dev", "qa", "prod"}, "verb": "create branch + 3 databases, seed V003",
                       "text": "production · app_dev_db + app_qa_db + app_prod_db"},
    "feature":        {"keys": {"devchild"}, "verb": "create child off production",
                       "text": "dev-* child of production · app_dev_db"},
    "migrate-branch": {"keys": {"devchild"}, "verb": "apply V004", "text": "dev-* child · app_dev_db"},
    "test-branch":    {"keys": {"devchild"}, "verb": "validate", "text": "dev-* child · app_dev_db"},
    "build":          {"keys": set(), "verb": "build artifact (no database)", "text": "— no branch / database —"},
    "dev-baseline":   {"keys": {"dev"}, "verb": "replay V004", "text": "production · app_dev_db"},
    "deploy-qa":      {"keys": {"qa"}, "verb": "replay V004", "text": "production · app_qa_db"},
    "prod-preflight": {"keys": {"preflight"}, "verb": "rehearse V004, then delete",
                       "text": "prod-preflight-* child · app_prod_db"},
    "deploy-prod":    {"keys": {"prod"}, "verb": "replay V004 (approved)", "text": "production · app_prod_db"},
    "cleanup":        {"keys": {"devchild"}, "verb": "delete child", "text": "dev-* child (deleted)", "danger": True},
}

LOCK = threading.Lock()
STATE = {"status": {sid: "pending" for sid in STAGE_IDS}, "log": [], "busy": False,
         "tree": [], "env": {}, "active": None}


def log(line):
    with LOCK:
        STATE["log"].append(line)
        STATE["log"] = STATE["log"][-400:]


def run_stage(sid):
    with LOCK:
        if STATE["busy"]:
            return
        STATE["busy"] = True
        STATE["status"][sid] = "running"
        STATE["active"] = sid
    stage = next(s for s in STAGES if s[0] == sid)
    log(f"\n━━━ {stage[1]} ━━━")
    ok = True
    try:
        env = dict(os.environ, DATABRICKS_CONFIG_PROFILE=PROFILE, MIGRATION_GIT_SHA=GIT_SHA,
                   PATH=VENV_BIN + os.pathsep + os.environ.get("PATH", ""))
        for disp, argv in stage[4]:
            log(f"$ {disp}")
            if argv is None:
                log("  (shown — runs in the real pipeline, not from this console)")
                continue
            p = subprocess.Popen(argv, cwd=REPO, env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, bufsize=1)
            for ln in p.stdout:
                log(ln.rstrip())
            if p.wait() != 0:
                ok = False
                log(f"  ✗ exited {p.returncode}")
                break
    except Exception as e:  # noqa: BLE001
        ok = False
        log(f"  ✗ {e}")
    with LOCK:
        STATE["status"][sid] = "done" if ok else "error"
        STATE["busy"] = False
    refresh_state()


def do_reset():
    with LOCK:
        if STATE["busy"]:
            return
        STATE["busy"] = True
    log("\n━━━ Reset demo (rewind V004 on all three databases, delete ephemeral branches) ━━━")
    try:
        w = lb.client(PROFILE)
        for br in (DEV_BRANCH, PROD_PREFLIGHT):
            lb.delete_branch(w, PROJECT, br)
            log(f"  - deleted {br}")
        rb = open(os.path.join(REPO, "db", "rollback", "V004__add_signup_source.sql")).read()
        for db in (DEV_DB, QA_DB, PROD_DB):
            conn = lb.connect(w, PROJECT, BRANCH, db)
            try:
                with conn.cursor() as cur:
                    cur.execute(rb)
                    cur.execute("DELETE FROM app.schema_migrations WHERE version='V004'")
                conn.commit()
                log(f"  ↩ rewound V004 on production/{db}")
            finally:
                conn.close()
    except Exception as e:  # noqa: BLE001
        log(f"  ✗ {e}")
    with LOCK:
        STATE["status"] = {sid: "pending" for sid in STAGE_IDS}
        STATE["busy"] = False
    refresh_state()


def refresh_state():
    """Pull the live branch tree + per-database schema version on production (off the UI thread)."""
    def worker():
        try:
            w = lb.client(PROFILE)
            tree = lb.list_branches(w, PROJECT)
        except Exception as e:  # noqa: BLE001
            with LOCK:
                STATE["tree"] = [{"branch": f"(cannot reach {PROFILE}: {str(e)[:50]})",
                                  "source": None, "state": None}]
            return
        env = {}
        for label, db in (("dev", DEV_DB), ("qa", QA_DB), ("prod", PROD_DB)):
            try:
                conn = lb.connect(w, PROJECT, BRANCH, db)
                with conn.cursor() as cur:
                    cur.execute("SELECT coalesce(max(version),'(none)') FROM app.schema_migrations")
                    ver = cur.fetchone()[0]
                    cur.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='app' "
                                "AND table_name='users' AND column_name='signup_source'")
                    src = "present" if cur.fetchone() else "absent"
                    cur.execute("SELECT count(*) FROM app.users")
                    n = cur.fetchone()[0]
                conn.close()
                env[label] = {"db": db, "version": ver, "signup_source": src, "users": n}
            except Exception as e:  # noqa: BLE001
                env[label] = {"db": db, "version": "?", "signup_source": str(e)[:30], "users": "?"}
        with LOCK:
            STATE["tree"] = tree
            STATE["env"] = env
    threading.Thread(target=worker, daemon=True).start()


# ----------------------------------------------------------------------------- UI
app = dash.Dash(__name__, title="Lakebase CI/CD Console")
PANEL = {"background": C["card"], "border": f"1px solid {C['line']}", "borderRadius": "10px", "padding": "16px"}


def pending_change():
    sql = open(os.path.join(REPO, "db", "migrations", "V004__add_signup_source.sql")).read()
    return html.Div(style=PANEL, children=[
        html.Div("THE PENDING CHANGE", style={"fontSize": "11px", "letterSpacing": ".08em",
                 "color": C["mut"], "fontWeight": 700}),
        html.Div("db/migrations/V004__add_signup_source.sql", style={"fontWeight": 600, "margin": "4px 0 8px"}),
        html.Pre(sql, style={"background": C["code"], "color": "#d7e7ff", "padding": "12px",
                 "borderRadius": "8px", "fontSize": "12px", "overflowX": "auto", "maxHeight": "240px", "margin": 0})])


BADGE = {"pending": ("○", C["mut"]), "running": ("●", C["run"]), "done": ("✓", C["ok"]), "error": ("✗", C["err"])}


def stage_card(stage):
    sid, title, _, blurb, cmds, api = stage
    return html.Div(style={**PANEL, "marginBottom": "10px", "borderLeft": f"4px solid {C['line']}"}, children=[
        html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"}, children=[
            html.Div([html.Span("○", id={"type": "badge", "sid": sid},
                                 style={"color": C["mut"], "fontWeight": 700, "marginRight": "8px"}),
                      html.Span(title, style={"fontWeight": 700})]),
            html.Button("Run", id={"type": "run", "sid": sid}, n_clicks=0,
                        style={"padding": "6px 16px", "borderRadius": "7px", "border": "none",
                               "background": C["accent"], "color": "#fff", "cursor": "pointer", "fontWeight": 600})]),
        html.Div([html.Span("ACTS ON  ", style={"fontSize": "10px", "letterSpacing": ".06em",
                  "color": C["mut"], "fontWeight": 700}),
                  html.Code(ACTS.get(sid, {}).get("text", "—"),
                            style={"fontSize": "12px", "color": C["accent"]})], style={"marginTop": "4px"}),
        html.Div(blurb, style={"color": C["mut"], "fontSize": "13px", "marginTop": "6px"}),
        html.Pre("\n".join("$ " + d for d, _ in cmds),
                 style={"background": C["code"], "color": "#d7e7ff", "padding": "10px", "borderRadius": "6px",
                        "fontSize": "12px", "overflowX": "auto", "margin": "8px 0"}),
        html.Div([html.Span("API ", style={"fontWeight": 700, "fontSize": "11px", "color": C["mut"]}),
                  html.Code(api, style={"fontSize": "12px"})])])


# Files viewable in the "Scripts" tab — the exact code each stage runs. (label, repo-relative path)
SCRIPTS = [
    ("ci/lakebase.sh — Lakebase control-plane wrapper (branches, databases, connections)", "ci/lakebase.sh"),
    ("ci/lakebase_api.py — SDK engine behind lakebase.sh (projects/branches/credentials)", "ci/lakebase_api.py"),
    ("ci/migrate.sh — migration runner (thin wrapper over migrate.py)", "ci/migrate.sh"),
    ("ci/migrate.py — migration runner engine (advisory lock, checksum, history)", "ci/migrate.py"),
    ("ci/seed.py — load non-production seed data", "ci/seed.py"),
    ("ci/check_migrations.sh — static migration-file checks", "ci/check_migrations.sh"),
    ("ci/build.sh — build the application artifact once from a Git SHA", "ci/build.sh"),
    ("ci/publish_artifact.sh — publish the artifact + record its SHA-256", "ci/publish_artifact.sh"),
    ("ci/fetch_artifact.sh — fetch + verify the exact artifact by digest", "ci/fetch_artifact.sh"),
    ("ci/deploy_preview.sh — preview deploy / discover-url / destroy helpers", "ci/deploy_preview.sh"),
    ("ci/uc.sh — Unity Catalog preview-schema helpers", "ci/uc.sh"),
    ("ci/smoke_test.sh — post-deploy smoke check", "ci/smoke_test.sh"),
    ("db/migrations/V004__add_signup_source.sql — the change this demo promotes", "db/migrations/V004__add_signup_source.sql"),
    ("db/roles/grants.sql — per-database role grants (the isolation boundary)", "db/roles/grants.sql"),
    ("databricks.yml — one bundle, five targets", "databricks.yml"),
    (".github/workflows/pr.yml — PR validation (ci-pr branch on app_dev_db)", ".github/workflows/pr.yml"),
    (".github/workflows/main-to-qa.yml — build → dev-baseline → QA", ".github/workflows/main-to-qa.yml"),
    (".github/workflows/promote-prod.yml — preflight → approval → PROD", ".github/workflows/promote-prod.yml"),
]
ALLOWED_SCRIPTS = {rel for _, rel in SCRIPTS}

# Plain-language glossary of the scripts that actually RUN during the walkthrough — shown at the
# top of the Scripts tab so the audience knows what each command is doing as you click through.
GLOSSARY = [
    ("lakebase.sh / lakebase_api.py", "Lakebase control plane. Creates & deletes branches and hands "
     "out a short-lived DB connection — never prints a credential. Runs in setup, start-change, "
     "preflight, cleanup, and whenever a stage needs a connection."),
    ("migrate.sh / migrate.py", "The migration runner. Applies the ordered db/migrations/*.sql to ONE "
     "database and records what ran (version + checksum + git SHA). This is the actual promotion: the "
     "same files replayed into app_dev_db → app_qa_db → app_prod_db."),
    ("check_migrations.sh", "Pre-flight lint of the migration files before any database is touched — "
     "names, ordering, and a warning on destructive SQL (step 2)."),
    ("seed.py", "Loads sample rows for validation only (setup). Seed data is never promoted."),
    ("build.sh", "Packages the app once into a tarball from the Git SHA (step 4)."),
    ("publish_artifact.sh / fetch_artifact.sh", "Publish records the tarball + its SHA-256; fetch "
     "downloads it and fails unless the digest matches — the 'same bytes everywhere' guarantee."),
    ("deploy_preview.sh", "Wraps `databricks bundle` for previews: quiesce, discover the app URL, "
     "destroy. (Shown in the stage commands; the bundle deploy itself is narrated, not run here.)"),
    ("uc.sh", "Creates/deletes per-PR Unity Catalog schemas — lakehouse scratch, separate from the "
     "Postgres app database."),
    ("smoke_test.sh", "Quick post-deploy check that the target database is reachable with the expected "
     "schema."),
]


app.layout = html.Div(style={"fontFamily": "system-ui,sans-serif", "background": C["bg"],
                             "color": C["ink"], "minHeight": "100vh", "padding": "20px"}, children=[
    dcc.Interval(id="tick", interval=1400, n_intervals=0),
    html.Div(style={"display": "flex", "alignItems": "baseline", "gap": "12px", "marginBottom": "4px"}, children=[
        html.H1("Lakebase CI/CD — Developer Lifecycle", style={"margin": 0, "fontSize": "22px"}),
        html.Span(f"one workspace · one branch `production` · 3 databases · project {PROJECT} · profile {PROFILE}",
                  style={"color": C["mut"], "fontSize": "13px"})]),
    html.Div("One long-lived branch holds app_dev_db / app_qa_db / app_prod_db · a change is promoted by "
             "replaying migrations dev → qa → prod across the databases · only code, artifacts, and migrations move forward",
             style={"color": C["mut"], "fontSize": "13px", "marginBottom": "16px"}),

    dcc.Tabs(id="tabs", value="walk", style={"marginBottom": "14px"}, children=[
        dcc.Tab(label="Walkthrough", value="walk"),
        dcc.Tab(label="Scripts", value="scripts")]),

    html.Div(id="tab-walk", children=[
      html.Div(id="diagram", style={**PANEL, "marginBottom": "16px"}),
      html.Div(style={"display": "grid", "gridTemplateColumns": "1.3fr 1fr", "gap": "16px"}, children=[
        html.Div(children=[
            html.Div(style={"display": "flex", "gap": "8px", "marginBottom": "12px"}, children=[
                html.Button("↻ Refresh live state", id="btn-refresh", n_clicks=0,
                            style={"padding": "8px 12px", "borderRadius": "8px", "border": f"1px solid {C['line']}",
                                   "background": C["card"], "cursor": "pointer"}),
                html.Button("⟲ Reset demo", id="btn-reset", n_clicks=0,
                            style={"padding": "8px 12px", "borderRadius": "8px", "border": f"1px solid {C['line']}",
                                   "background": C["card"], "cursor": "pointer"})]),
            html.Div(id="action-sink", style={"display": "none"}),
            html.Div([stage_card(s) for s in STAGES])]),
        html.Div(children=[
            html.Div(id="tree", style={**PANEL, "marginBottom": "16px"}),
            html.Div(id="envs", style={**PANEL, "marginBottom": "16px"}),
            pending_change(),
            html.Div(style={**PANEL, "marginTop": "16px"}, children=[
                html.Div("ACTIVITY LOG", style={"fontSize": "11px", "letterSpacing": ".08em",
                         "color": C["mut"], "fontWeight": 700, "marginBottom": "6px"}),
                html.Pre(id="log", style={"background": C["code"], "color": "#cfe3ff", "padding": "12px",
                         "borderRadius": "8px", "fontSize": "12px", "height": "220px", "overflowY": "auto", "margin": 0})])])])]),

    html.Div(id="tab-scripts", hidden=True, children=[
      html.Div(style={**PANEL, "marginBottom": "16px"}, children=[
        html.Div("WHAT RUNS DURING THE DEMO", style={"fontSize": "11px", "letterSpacing": ".08em",
                 "color": C["mut"], "fontWeight": 700, "marginBottom": "8px"}),
        *[html.Div(style={"display": "grid", "gridTemplateColumns": "230px 1fr", "gap": "12px",
                          "padding": "7px 0", "borderBottom": f"1px solid {C['line']}"},
                   children=[html.Code(name, style={"fontSize": "12.5px", "color": C["accent"],
                                                    "fontWeight": 600}),
                             html.Span(desc, style={"fontSize": "13px", "color": C["ink"]})])
          for name, desc in GLOSSARY],
        html.Div("Each stage card (Walkthrough tab) also prints the exact command + the underlying "
                 "Lakebase API call it runs.", style={"color": C["mut"], "fontSize": "12px", "marginTop": "10px"})]),
      html.Div(style=PANEL, children=[
        html.Div("READ THE FULL SOURCE", style={"fontSize": "11px", "letterSpacing": ".08em",
                 "color": C["mut"], "fontWeight": 700}),
        html.Div("The exact files the stages run — the ci/ scripts, the promoted migration, the bundle, and "
                 "the workflows. Pick one to read it; this is live from disk.",
                 style={"color": C["mut"], "fontSize": "13px", "margin": "4px 0 10px"}),
        dcc.Dropdown(id="script-pick", clearable=False, value="ci/lakebase.sh",
                     options=[{"label": lbl, "value": rel} for lbl, rel in SCRIPTS],
                     style={"maxWidth": "640px", "marginBottom": "10px"}),
        html.Pre(id="script-body", style={"background": C["code"], "color": "#d7e7ff", "padding": "14px",
                 "borderRadius": "8px", "fontSize": "12.5px", "lineHeight": "1.5", "overflow": "auto",
                 "maxHeight": "72vh", "margin": 0})])]),
])


@app.callback(Output({"type": "badge", "sid": dash.ALL}, "children"),
              Output({"type": "badge", "sid": dash.ALL}, "style"),
              Input("tick", "n_intervals"))
def render_badges(_):
    with LOCK:
        st = dict(STATE["status"])
    glyphs, styles = [], []
    for sid in STAGE_IDS:
        g, col = BADGE[st[sid]]
        glyphs.append(g)
        styles.append({"color": col, "fontWeight": 700, "marginRight": "8px"})
    return glyphs, styles


def diagram_children(active, status):
    """Topology diagram that highlights the branch + database the active stage acts on."""
    act = ACTS.get(active or "", {})
    hl = act.get("keys", set())
    danger = act.get("danger", False)
    hc = C["err"] if danger else C["run"] if status == "running" else C["ok"] if status == "done" else C["accent"]
    tint = {C["accent"]: C["accent2"], C["ok"]: "#e8f6ee", C["run"]: "#fdf1df", C["err"]: "#fbe9e9"}

    def cell(key, label, sub):
        on = key in hl
        return html.Div(style={"flex": "1", "minWidth": "110px", "padding": "9px 10px", "borderRadius": "8px",
                               "textAlign": "center", "border": f"2px solid {hc if on else C['line']}",
                               "background": tint[hc] if on else C["card"]},
                        children=[html.Div(label, style={"fontWeight": 700, "fontSize": "13px",
                                           "color": hc if on else C["ink"]}),
                                  html.Div(sub, style={"fontSize": "11px", "color": C["mut"], "marginTop": "2px"}),
                                  html.Div("◀ acting now", style={"fontSize": "10px", "fontWeight": 700,
                                           "color": hc, "marginTop": "3px"}) if on else html.Div()])

    prod_on = bool(hl & {"dev", "qa", "prod"})
    production = html.Div(style={"border": f"2px solid {hc if prod_on else C['line']}", "borderRadius": "10px",
                                 "padding": "10px", "background": tint[hc] + "55" if prod_on else C["bg"]}, children=[
        html.Div("production — the one long-lived branch", style={"fontWeight": 700, "fontSize": "12px",
                 "color": hc if prod_on else C["ink"], "marginBottom": "8px"}),
        html.Div(style={"display": "flex", "gap": "10px"}, children=[
            cell("dev", "app_dev_db", "DEV baseline"),
            cell("qa", "app_qa_db", "QA"),
            cell("prod", "app_prod_db", "PROD")])])

    ephemeral = html.Div(style={"marginTop": "10px"}, children=[
        html.Div("ephemeral children of production (created on demand, never promoted)",
                 style={"fontSize": "11px", "color": C["mut"], "marginBottom": "6px"}),
        html.Div(style={"display": "flex", "gap": "10px"}, children=[
            cell("devchild", "dev-* / ci-pr-*", "selects app_dev_db"),
            cell("preflight", "prod-preflight-*", "selects app_prod_db")])])

    if active:
        cap = f"Now acting on:  {act.get('text','—')}   —   {act.get('verb','')}  ({status})"
        capcol = hc
    else:
        cap = "Run a stage to see which branch and database it acts on."
        capcol = C["mut"]
    return [html.Div("WHERE THIS STAGE ACTS", style={"fontSize": "11px", "letterSpacing": ".08em",
                     "color": C["mut"], "fontWeight": 700, "marginBottom": "8px"}),
            production, ephemeral,
            html.Div(cap, style={"marginTop": "10px", "fontSize": "13px", "fontWeight": 600, "color": capcol})]


@app.callback(Output("diagram", "children"), Input("tick", "n_intervals"))
def render_diagram(_):
    with LOCK:
        active = STATE.get("active")
        status = STATE["status"].get(active) if active else None
    return diagram_children(active, status)


@app.callback(Output("tab-walk", "hidden"), Output("tab-scripts", "hidden"), Input("tabs", "value"))
def switch_tab(v):
    # toggle visibility (components stay mounted, so the interval callbacks keep finding them)
    return v != "walk", v != "scripts"


@app.callback(Output("script-body", "children"), Input("script-pick", "value"))
def show_script(path):
    if path not in ALLOWED_SCRIPTS:
        return "(unknown file)"
    try:
        with open(os.path.join(REPO, path), encoding="utf-8") as f:
            return f.read()
    except Exception as e:  # noqa: BLE001
        return f"(cannot read {path}: {e})"


@app.callback(Output("tree", "children"), Output("envs", "children"), Output("log", "children"),
              Input("tick", "n_intervals"))
def render_right(_):
    with LOCK:
        tree, env, logs = list(STATE["tree"]), dict(STATE["env"]), "\n".join(STATE["log"])

    def row(r):
        b = r["branch"]
        tag, col = "", C["mut"]
        if b == "production":
            tag, col = "long-lived → app_dev_db + app_qa_db + app_prod_db", C["ink"]
        elif b.startswith(("ci-pr-", "dev-")):
            tag, col = "ephemeral child → selects app_dev_db", C["accent"]
        elif "qa-preflight" in b:
            tag, col = "ephemeral rehearsal → app_qa_db", C["run"]
        elif "prod-preflight" in b:
            tag, col = "ephemeral rehearsal → app_prod_db", C["run"]
        return html.Div(style={"display": "flex", "justifyContent": "space-between", "padding": "4px 0",
                               "borderBottom": f"1px solid {C['line']}"},
                        children=[html.Span(b, style={"fontWeight": 600, "color": col}),
                                  html.Span(tag, style={"fontSize": "12px", "color": C["mut"]})])

    tree_el = [html.Div("LAKEBASE BRANCH TREE", style={"fontSize": "11px", "letterSpacing": ".08em",
               "color": C["mut"], "fontWeight": 700, "marginBottom": "6px"})] + \
        ([row(r) for r in tree] if tree else [html.Div("(click ↻ Refresh live state)", style={"color": C["mut"]})])

    def envcard(name):
        e = env.get(name, {})
        hs = e.get("signup_source", "?")
        hcol = C["ok"] if hs == "present" else C["mut"]
        return html.Div(style={"padding": "6px 0", "borderBottom": f"1px solid {C['line']}"}, children=[
            html.Div(f"{name.upper()} — production / {e.get('db','?')}", style={"fontWeight": 600}),
            html.Div([html.Span(f"schema {e.get('version','?')}  ·  users {e.get('users','?')}  ·  "),
                      html.Span(f"signup_source {hs}", style={"color": hcol, "fontWeight": 600})],
                     style={"fontSize": "12px", "color": C["mut"]})])

    env_el = [html.Div("DATABASES ON production (live)", style={"fontSize": "11px", "letterSpacing": ".08em",
              "color": C["mut"], "fontWeight": 700, "marginBottom": "6px"}),
              envcard("dev"), envcard("qa"), envcard("prod")]
    return tree_el, env_el, logs or "(idle)"


@app.callback(Output("action-sink", "children"),
              Input({"type": "run", "sid": dash.ALL}, "n_clicks"),
              Input("btn-reset", "n_clicks"), Input("btn-refresh", "n_clicks"),
              prevent_initial_call=True)
def on_action(run_clicks, reset_clicks, refresh_clicks):
    trig = dash.callback_context.triggered_id
    if trig == "btn-refresh":
        refresh_state()
    elif trig == "btn-reset":
        threading.Thread(target=do_reset, daemon=True).start()
    elif isinstance(trig, dict) and trig.get("type") == "run":
        threading.Thread(target=run_stage, args=(trig["sid"],), daemon=True).start()
    return ""


if __name__ == "__main__":
    refresh_state()
    app.run(debug=False, port=int(os.environ.get("DEMO_PORT", "8052")))

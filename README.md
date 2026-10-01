# Lakebase CI/CD Template — one branch, a database per environment

A **clone-and-adapt reference** for a safe Git + Lakebase + Databricks developer lifecycle for a
small team (2–4 developers) on a **single Databricks workspace**, where DEV / QA / PROD are
**separate Lakebase databases on one long-lived branch** and every change is validated on a
**short-lived branch cut from that one branch**.

It is a working template, not a slide: the migration runner, the Lakebase control-plane wrapper,
the bundle, and the GitHub Actions workflows all run. A guided **console app** walks the whole
lifecycle and shows the exact command and API call behind every step.

---

## The model in one picture

```
                         ONE DATABRICKS WORKSPACE  (shared by DEV / QA / PROD)
                                        │
          ┌─────────────────────────────┴─────────────────────────────┐
   Unity Catalog (lakehouse objects)                        Lakebase project  "lakebase-app"
   app_dev / app_qa / app_prod                                        │
   (parallel to Lakebase, not bound)                      production  ← the ONLY long-lived branch
                                                            ├── app_dev_db     DEV baseline + DEV/PR source
                                                            ├── app_qa_db      QA
                                                            └── app_prod_db    PROD
                                                           ephemeral children of production:
                                                            ├── ci-pr-<n>   / dev-<who>-*  → select app_dev_db
                                                            ├── qa-preflight-<sha>          → selects app_qa_db
                                                            └── prod-preflight-<sha>        → selects app_prod_db
```

- **One workspace, one branch.** `production` is the only long-lived Lakebase branch, and it hosts
  all three databases. There is **no long-lived dev or qa branch**. The workspace is *not* a
  security boundary — isolation comes from per-database PostgreSQL roles, UC catalog/schema grants,
  per-environment service principals, pipeline allowlists, and a production approval gate.
- **A database per environment.** `app_dev_db`, `app_qa_db`, `app_prod_db` all live on `production`
  and share its compute/lifecycle. DEV/QA/PROD are separated by **database (and role)**, not branch.
- **Branch per change.** Every PR (and dev session) gets a disposable child of `production` that
  **selects `app_dev_db`**. The child contains all three databases, but the workflow uses only its
  one — enforced by the explicit `lakebase_database` selector and per-database roles.
- **Promotion = replaying migrations across databases.** The same ordered `V###__*.sql` files are
  replayed into `production/app_dev_db` (post-merge DEV baseline) → `production/app_qa_db` →
  `production/app_prod_db` (after approval). Same branch every time; only the **database** changes.
  You never merge or copy a Lakebase branch. **Only code, immutable artifacts, and migration files
  move forward** — never application data, test rows, or branch-local state.

The full reasoning is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Quickstart: the guided console

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r demo/requirements.txt   # use the venv's own pip

databricks auth login --profile lakebase-dev               # your single workspace profile
DEMO_PROFILE=lakebase-dev DEMO_PROJECT=lakebase-app .venv/bin/python demo/console.py
# open http://127.0.0.1:8052
```

The console runs each stage's commands as subprocesses using **this same interpreter**, so launch
it with `.venv/bin/python` (the venv that has the SDK, psycopg, and dash). No `activate` needed.

Walk the stages 0 → 9. Each card shows the command, the underlying Lakebase API call, and a **Run**
button. Watch the right-hand panel: the three databases on `production` flip from V003 to V004 one
at a time (dev → qa → prod) as you promote, and the ephemeral child branches appear and disappear.
**Reset demo** rewinds the headline change (V004) across all three databases. Presenter script:
[`demo/DEMO_SCRIPT.md`](demo/DEMO_SCRIPT.md).

---

## Quickstart: the same lifecycle from the CLI

```bash
export DATABRICKS_CONFIG_PROFILE=lakebase-dev

# 0. one-time platform setup: project + production + the three databases
./ci/lakebase.sh init lakebase-app
for db in app_dev_db app_qa_db app_prod_db; do
  python ci/migrate.py --project lakebase-app --branch production --database "$db" --to V003
  python ci/seed.py    --project lakebase-app --branch production --database "$db"
done

# 1. start a change: child of production selecting app_dev_db
./ci/lakebase.sh prepare-ci-branch lakebase-app dev-me-signup-source --source-branch production --database app_dev_db

# 2. apply migrations on the branch (only V004 is pending)
./ci/check_migrations.sh db/migrations
python ci/migrate.py --project lakebase-app --branch dev-me-signup-source --database app_dev_db

# 5-8. promote by REPLAYING the migration set across the databases on production
python ci/migrate.py --project lakebase-app --branch production --database app_dev_db    # DEV baseline (post-merge)
python ci/migrate.py --project lakebase-app --branch production --database app_qa_db     # QA
./ci/lakebase.sh create-preflight prod-preflight-$USER lakebase-app --source-branch production
python ci/migrate.py --project lakebase-app --branch prod-preflight-$USER --database app_prod_db   # rehearse
./ci/lakebase.sh delete-ci-branch prod-preflight-$USER lakebase-app
python ci/migrate.py --project lakebase-app --branch production --database app_prod_db   # the approved prod step

# inspect the tree at any time
./ci/lakebase.sh tree lakebase-app
```

In CI the connection URL is minted and exported instead of passing `--project/--branch`:
`eval "$(./ci/lakebase.sh wait-and-export lakebase-app ci-pr-7 app_dev_db)"` then
`DATABASE_URL=$LAKEBASE_DATABASE_URL ./ci/migrate.sh`.

---

## Repository layout

```
app/            sample app under promotion (user directory) + its tests
db/migrations/  ordered, immutable V###__*.sql — the source of truth for schema changes
db/seeds/       non-production sample data (validation only, never promoted)
db/roles/       per-database PostgreSQL role + grant bootstrap (owner/migrator/runtime per db)
db/rollback/    demo-only rewind of V004 (production is forward-only; see ARCHITECTURE.md)
ci/             lakebase.sh / migrate.py / seed.py / build + artifact + preview + uc + smoke
resources/      bundle resources (the app, an illustrative job)
databricks.yml  one bundle, five targets: dev-preview, qa-preflight, qa, prod-preflight, prod
.github/workflows/  pr.yml, main-to-qa.yml (build → dev-baseline → qa), promote-prod.yml
demo/           the guided console app + presenter script
docs/           architecture reference distilled from the runbook
```

---

## The deployment tuple (the one-workspace, one-branch guardrail)

Because one workspace and one branch host every environment, **every** deployment names all of its
selectors explicitly — above all the **database**, since the branch is the same for QA and PROD:

| Env         | Branch               | Database      | UC catalog/schema      | CI identity              | Bundle namespace      | Connection ref                           |
|-------------|----------------------|---------------|------------------------|--------------------------|-----------------------|------------------------------------------|
| PR preview  | `ci-pr-<n>`          | `app_dev_db`  | `app_dev.pr_<n>` (UC)  | `sp-app-dev-cicd`        | `dev/pr-<n>`          | `lakebase/dev/ci-pr-<n>/app_dev_db`      |
| DEV baseline| `production`         | `app_dev_db`  | `app_dev` (UC)         | `sp-app-dev-cicd`        | `dev`                 | `lakebase/dev/production/app_dev_db`     |
| QA          | `production`         | `app_qa_db`   | `app_qa.app`           | `sp-app-qa-cicd`         | `qa`                  | `lakebase/qa/production/app_qa_db`       |
| PROD preflt | `prod-preflight-sha` | `app_prod_db` | `app_prod.preflight_*` | `sp-app-prod-preflight`  | `prod-preflight-<sha>`| `lakebase/prod/prod-preflight-sha/...`   |
| PROD        | `production`         | `app_prod_db` | `app_prod.app`         | `sp-app-prod-cicd`       | `prod`                | `lakebase/prod/production/app_prod_db`   |

No human or DEV identity may write `app_prod.app` or `production/app_prod_db`. The promotion
invariant: **same Git SHA + same artifact digest + same ordered migration set + explicit tuple.**

## Per-database roles

Because the three databases share one branch, PostgreSQL roles are the real isolation boundary.
Each database has an `*_owner`, `*_migrator`, and `*_runtime` role; `CONNECT`/`TEMPORARY`/`CREATE`
are revoked from `PUBLIC` and granted only to that database's roles. See
[`db/roles/`](db/roles) for the version-controlled bootstrap SQL and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the contract and the cross-database denial tests.

---

## Make it your own

1. Replace the sample app in `app/` and the migrations in `db/migrations/` with yours.
2. Set `workspace_host` and the `*_service_principal` variables in `databricks.yml` (or via
   `BUNDLE_VAR_*`); point `LAKEBASE_PROJECT` at your project.
3. Configure GitHub OIDC → per-environment service principals and the `dev`/`qa`/`prod-preflight`/
   `prod` GitHub environments with a required approval on `prod`. Pin every action to an approved
   commit (the workflows ship with `<approved-pinned-commit>` placeholders on purpose).
4. Apply the per-database role bootstrap in `db/roles/` with a privileged identity.
5. Validate before handoff:
   ```bash
   actionlint .github/workflows/*.yml
   for t in dev-preview qa-preflight qa prod-preflight prod; do databricks bundle validate --target "$t"; done
   ```

To run against a brand-new workspace, see **Run against a fresh workspace** below.

---

## Run against a fresh workspace

Nothing here is tied to the workspace it was built in — the only workspace-specific input is the
CLI **profile**. Everything else (project, branch, databases, schema, seed data) is created from
scratch by **Step 0**.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r demo/requirements.txt
databricks auth login --profile <new-ws>
DEMO_PROFILE=<new-ws> DEMO_PROJECT=lakebase-app .venv/bin/python demo/console.py
#   then click "Step 0 · Platform setup + baseline"  →  provisions project + production + 3 databases
```

**What the target workspace needs:** Lakebase enabled in that workspace/region; your identity can
create Lakebase projects/branches/databases (project-level CAN MANAGE); the venv on the machine
running the console. The console and CLI promotion need only the profile; the GitHub Actions +
`databricks bundle deploy` path additionally needs `BUNDLE_VAR_workspace_host`, the per-environment
service principals, and the GitHub OIDC/environment setup under **Make it your own**.

This template adapts the internal *Git + Lakebase Branching and CI/CD Runbook*. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the mental model, identity planes, migration
rules, and reset/hotfix procedures.

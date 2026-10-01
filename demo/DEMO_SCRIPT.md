# Presenter script — Lakebase CI/CD developer lifecycle (one branch, a database per environment)

A ~15-minute walkthrough using the guided console (`.venv/bin/python demo/console.py`,
http://127.0.0.1:8052). The console runs each step live, so the three per-database panels and the
branch tree change as you talk. Each stage card shows the command and the API call.

**Before you start:** `databricks auth login --profile <ws>`, then run stage **0** once (or
`Reset demo`) so you open on a clean baseline: all three databases on `production` — `app_dev_db`,
`app_qa_db`, `app_prod_db` — at **schema V003**, `signup_source absent`. The headline change
**V004 — add `signup_source`** is shown in the panel.

---

### Opening line
> "This customer runs everything on *one* Databricks workspace and *one* long-lived Lakebase branch,
> `production`. DEV, QA, and PROD aren't separate branches — they're separate *databases* on that one
> branch: `app_dev_db`, `app_qa_db`, `app_prod_db`. Watch a schema change travel across those three
> databases without ever copying one — only the migration file moves."

### Stage 1 — Start the change
Click **Run**. A `dev-demo-signup-source` branch appears, tagged *ephemeral child → selects app_dev_db*.
> "A copy-on-write child of `production`. It contains all three databases, but my workflow uses only
> `app_dev_db` — so I'm testing my change against the DEV baseline in isolation. It's never promoted."

### Stage 2 — Apply the migration on the branch
Click **Run**. `check_migrations` passes; `V004` applied to the child's `app_dev_db`.
> "V001–V003 are already here. Only V004 is pending. The runner locks, checksums, and would refuse
> any edit to a migration that's already been applied." Note: the three `production` databases are untouched.

### Stage 3 — Validate on the branch
Click **Run**. Unit tests pass; validate shows 0 pending.
> "In CI this is also where the *cross-database denial test* runs — proving the DEV role cannot even
> connect to `app_qa_db` or `app_prod_db`. On a single branch, roles are the real boundary."

### Stage 4 — Merge → build once
Click **Run**. A digest prints.
> "On merge we build *once* and record a SHA-256. Every database deploys these exact bytes."

### Stage 5 — DEV baseline  *(the new step)*
Click **Run**. The **DEV** panel flips to **V004 · signup_source present**.
> "This is new in the revised model: right after merge we replay the migration into
> `production/app_dev_db` — the shared DEV baseline every future feature branch is cut from. We keep
> DEV current ahead of the team."

### Stage 6 — Deploy to QA
Click **Run**. The **QA** panel flips to **V004 · present**.
> "Same migration file, same branch — only the database selector changes to `app_qa_db`. Promotion
> is a replay across databases, not a branch merge."

### Stage 7 — Production preflight
Click **Run**. A `prod-preflight-demo` branch appears tagged *selects app_prod_db*, the migration is
rehearsed, then it disappears.
> "A dress rehearsal on a throwaway child of `production` that selects `app_prod_db`. If it's going to
> misbehave on production-shaped data, it fails here — then we destroy the rehearsal."

### Stage 8 — Approve → deploy to PROD
> "The only step that touches the production database, behind a required approval in the real
> pipeline." Click **Run**. The **PROD** panel flips to **V004 · present**.
> "Same migration, same verified artifact, now on `production/app_prod_db`."

### Stage 9 — Clean up
Click **Run**. The `dev-demo-signup-source` branch disappears.
> "Ephemeral branches are disposable; a TTL sweep catches orphans. The `production` branch and its
> three databases remain."

### Close
Point at the panels: all three databases now at V004; the tree back to just `production`.
> "One workspace, one branch, a database per environment, and promotion by replaying migrations
> dev → qa → prod. It's a template in the repo — the commands you watched are the same `ci/` scripts
> and GitHub Actions a customer clones and adapts."

**To run it again:** click **Reset demo** (rewinds V004 on all three databases, deletes the
ephemeral branches).

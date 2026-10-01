# Architecture reference

Distilled from the internal *Git + Lakebase Branching and CI/CD Runbook*. This is the "why" behind
the template; the README is the "how".

## 1. Two coordinated version-control systems

```
Git:      feature/APP-204 ──PR──▶ main ──build once──▶ artifact + sha256
                                     │
                                     ├──▶ DEV baseline deploy
                                     ├──▶ QA deploy
                                     └──▶ PROD deploy (approval-gated)

Lakebase: production  (the only long-lived branch — hosts all three databases)
             ├── app_dev_db   ◀─ replay migrations (post-merge DEV baseline; source for children)
             ├── app_qa_db    ◀─ replay migrations (QA)
             └── app_prod_db  ◀─ replay migrations (PROD, after approval)
          ci-pr-N / dev-*       child of production, selects app_dev_db ──migrate + test──▶ deleted
          qa-preflight-SHA      child of production, selects app_qa_db  ──rehearse──▶ deleted
          prod-preflight-SHA    child of production, selects app_prod_db ──rehearse──▶ deleted
```

Git holds code and migration files. The one long-lived Lakebase branch holds three databases;
disposable children (copy-on-write, their own endpoint) are where changes are validated. The
**source of truth for a schema change is the migration file in Git** — promoted by replaying it
into each database in order, never by merging or copying a Lakebase branch.

## 2. One workspace, one branch — separated by database and role

A single workspace and a single branch remove hard infrastructure boundaries. The controls that
replace them, implemented or documented here:

- **Per-database PostgreSQL roles** — the real isolation boundary (§5).
- Unity Catalog catalog/schema grants (`app_dev` / `app_qa` / `app_prod`).
- An explicit **`lakebase_database` selector on every step** — the branch is identical for QA and
  PROD, so the database is what distinguishes them, and a child contains all three.
- Per-environment service principals and separate secret references.
- Pipeline branch/database allowlists + a required approval on the `prod` GitHub environment.
- Isolated bundle namespaces per environment and per PR.
- Native protected-branch + break-glass controls on `production` (a reset/delete affects all three
  databases, so it is tightly controlled).

If hard infrastructure separation is ever required, keep the shared workspace but use **separate
Lakebase projects** per environment.

## 3. Naming and lifecycle

| Artifact                | Convention                              | Lifetime                                   |
|-------------------------|-----------------------------------------|--------------------------------------------|
| Git feature branch      | `feature/<ticket>-<desc>`               | until PR merge/close                       |
| Stable branch           | `production`                            | long-lived; native protected; 3 databases  |
| DEV database            | `app_dev_db` on `production`            | maintained by post-merge replay; children's source |
| QA database             | `app_qa_db` on `production`             | post-merge QA validation / acceptance      |
| PROD database           | `app_prod_db` on `production`           | approved production target                 |
| PR database branch      | `ci-pr-<n>` (child of `production`)     | ephemeral, selects `app_dev_db`, TTL ~4h   |
| Personal dev branch     | `dev-<who>-<desc>` (child of `production`) | ephemeral, selects `app_dev_db`         |
| QA preflight            | `qa-preflight-<sha>` (child of `production`) | selects `app_qa_db`; until QA validation |
| PROD preflight          | `prod-preflight-<sha>` (child of `production`) | selects `app_prod_db`; until PROD validation |

Use the Git commit SHA in deployment records and artifact names; never a mutable `latest`.
Ephemeral branches carry TTLs; a scheduled job sweeps orphans.

## 4. Three identity planes

```
CI orchestrator   GitHub OIDC → Databricks service principal
                    ├── Lakebase control plane: create/manage/discover branches
                    └── Databricks deploy plane: validate/deploy bundle resources
Migration identity  per-database PostgreSQL role (CREATE/ALTER/INDEX/GRANT) — e.g. app_qa_migrator
Application identity per-database PostgreSQL role (DML only, no DDL)        — e.g. app_qa_runtime
```

The CI service principal is not a Postgres superuser. Migrations run as the database's migration
role; the app runs as its runtime role. `ci/migrate.py` substitutes `${APP_ROLE}` in grant
statements with the environment's runtime role.

## 5. Per-database roles (the real boundary)

Because the three databases share one branch, PostgreSQL roles — not the branch — enforce
isolation. Each database has an `*_owner` (non-login), `*_migrator` (DDL + migration history), and
`*_runtime` (DML only) role. The bootstrap in [`db/roles/`](../db/roles):

- revokes `CONNECT`, `TEMPORARY`, `CREATE` on each database from `PUBLIC`, then grants `CONNECT`
  only to that database's migration and runtime roles;
- revokes schema `PUBLIC` access and grants `USAGE`/`CREATE` to the migrator, `USAGE` to the runtime;
- uses `ALTER DEFAULT PRIVILEGES FOR ROLE <db>_migrator` so future tables/sequences created by the
  migrator are automatically readable/writable by the runtime role;
- revokes every cross-environment role membership so no DEV identity can connect to `app_qa_db` or
  `app_prod_db`.

CI runs **cross-database denial tests** (`ci/permission-tests.sh` in the runbook) on every PR
branch — a successful unauthorized connect or schema write is a deployment-blocking error.

## 6. Migration rules

- **Expand-and-contract.** Add nullable columns / new tables, deploy code that reads both shapes,
  backfill, switch, remove the old shape later. `V004` demonstrates the expand step.
- **Never edit an applied migration.** `ci/migrate.py` stores a checksum per applied version and
  fails on drift. Fix mistakes with a *new* migration.
- **Separate schema from data.** Promote migration files and migration-managed reference data.
  Never promote developer test rows, QA results, or application-generated data.
- **Lock + record.** Each run takes a Postgres advisory lock, applies pending migrations in order
  in one transaction, and records version, checksum, git SHA, and artifact SHA-256. The lock is
  taken **per database** (`production/app_dev_db`, `/app_qa_db`, `/app_prod_db`).

## 7. Build once, verify everywhere

On merge to `main`, build once, publish with a SHA-256 digest, and have every database deploy
**those same bytes**. The production job fails if the digest doesn't match the QA-approved manifest
(`qa-approvals/<sha>.json`). An auditable **emergency-authorization** path can waive the QA manifest
for incident hotfixes while still running the PROD preflight.

## 8. Reset, refresh, hotfix

- **Refresh a dev branch:** delete and recreate the child from `production` (selecting `app_dev_db`),
  reapply migrations, re-test. A parent cannot be reset while it has children — keep trees shallow.
- **Refresh the DEV or QA database:** refresh only that database on `production` via the approved
  procedure — never reset the `production` branch (it would affect all three databases).
- **Failed deployment:** redeploy the previous immutable artifact if code is bad but schema is
  compatible; use a forward corrective migration (not a blind branch reset) if a destructive change
  reached production; follow the incident process.
- **Hotfix:** `hotfix/<ticket>` from `main`, a preflight child from `production` selecting the
  intended database, normal CI gates (never bypass migration validation), then build-once →
  DEV baseline → QA → PROD. Emergency promotion requires a signed authorization record.

## Promotion invariant

```
same Git SHA + same artifact digest + same ordered migration set
+ explicit { project, branch=production, DATABASE, UC catalog/schema, identity, bundle namespace, connection ref }
```

The **database** selector is what the single-branch model turns on — carry it on every step.

# Per-database roles

DEV / QA / PROD are three databases on one Lakebase branch (`production`), so PostgreSQL roles are
the isolation boundary. Apply this bootstrap once with a privileged identity, after the databases
exist (`./ci/lakebase.sh init lakebase-app`):

```bash
# roles.sql is database-agnostic; grants.sql uses \connect to switch between the three databases.
psql "$BOOTSTRAP_DATABASE_URL" -f db/roles/roles.sql
psql "$BOOTSTRAP_DATABASE_URL" -f db/roles/grants.sql
```

Then grant each CI service principal membership in **only** the roles its environment may assume,
and revoke every cross-environment membership:

```sql
GRANT app_dev_migrator,  app_dev_runtime  TO "sp-app-dev-cicd";
GRANT app_qa_migrator,   app_qa_runtime   TO "sp-app-qa-cicd";
GRANT app_prod_migrator, app_prod_runtime TO "sp-app-prod-cicd";       -- prod deploy only
-- prod preflight SP gets app_prod_* for the rehearsal child only
```

Verify with cross-database denial tests (the runbook's `ci/permission-tests.sh`): assert that
`app_dev_runtime` cannot connect to `app_qa_db` or `app_prod_db`, and that no runtime role can write
another database's schema. A successful unauthorized connect or write is a deployment-blocking error.

> The guided demo and the `ci/migrate.py` runner connect as the current Databricks identity and do
> not require these roles to exist — they are the production isolation contract you apply before a
> real pipeline runs, kept here as version-controlled, idempotent SQL rather than console changes.

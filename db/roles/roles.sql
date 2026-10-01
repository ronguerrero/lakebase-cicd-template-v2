-- Per-database role triples. Idempotent. Run ONCE with a privileged bootstrap identity.
--
-- Because DEV / QA / PROD are three databases on ONE Lakebase branch, PostgreSQL roles — not the
-- branch — are the isolation boundary. Each database gets a non-login owner, a migration role
-- (DDL + migration history), and a runtime role (DML only). CI service principals are granted
-- MEMBERSHIP in exactly the roles their environment is allowed to assume (see db/roles/README.md).

DO $$ BEGIN CREATE ROLE app_dev_owner    NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE app_dev_migrator NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE app_dev_runtime  NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN CREATE ROLE app_qa_owner     NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE app_qa_migrator  NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE app_qa_runtime   NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN CREATE ROLE app_prod_owner    NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE app_prod_migrator NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE app_prod_runtime  NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;

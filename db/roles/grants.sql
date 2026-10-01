-- Per-database grants. Idempotent. Run AFTER roles.sql, with a privileged bootstrap identity.
--
-- PostgreSQL grants CONNECT and TEMPORARY on databases to PUBLIC by default, so selected-role
-- grants alone are not an isolation boundary — these blocks revoke the PUBLIC defaults first, then
-- grant CONNECT only to the database's own roles. `ALTER DEFAULT PRIVILEGES FOR ROLE <db>_migrator`
-- makes future tables/sequences created by the migrator automatically usable by the runtime role
-- (PostgreSQL applies new-object defaults from the creating role, not from owner membership).
-- The \connect meta-commands require psql; run as:  psql -f db/roles/grants.sql

-- DEV --------------------------------------------------------------------------
\connect app_dev_db
REVOKE CONNECT, TEMPORARY, CREATE ON DATABASE app_dev_db FROM PUBLIC;
GRANT CONNECT ON DATABASE app_dev_db TO app_dev_migrator, app_dev_runtime;
REVOKE ALL ON SCHEMA app FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA app TO app_dev_migrator;
GRANT USAGE ON SCHEMA app TO app_dev_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE app_dev_migrator IN SCHEMA app REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE app_dev_migrator IN SCHEMA app GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_dev_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE app_dev_migrator IN SCHEMA app REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE app_dev_migrator IN SCHEMA app GRANT USAGE, SELECT ON SEQUENCES TO app_dev_runtime;

-- QA ---------------------------------------------------------------------------
\connect app_qa_db
REVOKE CONNECT, TEMPORARY, CREATE ON DATABASE app_qa_db FROM PUBLIC;
GRANT CONNECT ON DATABASE app_qa_db TO app_qa_migrator, app_qa_runtime;
REVOKE ALL ON SCHEMA app FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA app TO app_qa_migrator;
GRANT USAGE ON SCHEMA app TO app_qa_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE app_qa_migrator IN SCHEMA app REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE app_qa_migrator IN SCHEMA app GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_qa_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE app_qa_migrator IN SCHEMA app REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE app_qa_migrator IN SCHEMA app GRANT USAGE, SELECT ON SEQUENCES TO app_qa_runtime;

-- PROD -------------------------------------------------------------------------
\connect app_prod_db
REVOKE CONNECT, TEMPORARY, CREATE ON DATABASE app_prod_db FROM PUBLIC;
GRANT CONNECT ON DATABASE app_prod_db TO app_prod_migrator, app_prod_runtime;
REVOKE ALL ON SCHEMA app FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA app TO app_prod_migrator;
GRANT USAGE ON SCHEMA app TO app_prod_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE app_prod_migrator IN SCHEMA app REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE app_prod_migrator IN SCHEMA app GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_prod_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE app_prod_migrator IN SCHEMA app REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE app_prod_migrator IN SCHEMA app GRANT USAGE, SELECT ON SEQUENCES TO app_prod_runtime;

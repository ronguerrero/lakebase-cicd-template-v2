-- V004: Capture where each user signed up from.
--
-- *** This is the change the demo promotes end to end: feature branch -> PR branch ->
--     QA -> prod preflight -> production, replaying this one file at each stop. ***
--
-- It models expand-and-contract step 1 (EXPAND):
--   * add a NULLABLE column    -> old code that never writes it keeps working
--   * backfill existing rows   -> controlled, idempotent, safe to re-run
--   * add a reporting view     -> what analysts and the app read
--   * grant the app role       -> permissions travel with the migration, as code
-- A later release would do step 2 (CONTRACT): make it NOT NULL / drop the old path.

ALTER TABLE app.users
    ADD COLUMN IF NOT EXISTS signup_source TEXT;

UPDATE app.users
   SET signup_source = 'legacy_import'
 WHERE signup_source IS NULL;

CREATE OR REPLACE VIEW app.v_users_by_source AS
    SELECT COALESCE(signup_source, 'unknown') AS signup_source,
           status,
           count(*) AS user_count
      FROM app.users
     GROUP BY 1, 2;

-- Grants are code too. ${APP_ROLE} is substituted by ci/migrate.sh with the environment's
-- application PostgreSQL role (the deployed app's identity), never the migration role.
GRANT SELECT ON app.v_users_by_source TO "${APP_ROLE}";

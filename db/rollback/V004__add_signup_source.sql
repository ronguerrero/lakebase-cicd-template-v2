-- Demo-only backward step for V004.
--
-- Production discipline (see the runbook, "Migration rules") is forward-only: you never edit
-- an applied migration and you fix mistakes with a NEW migration. This file exists ONLY so the
-- demo can rewind the headline change and run it again against the same branches. It is NOT
-- wired into ci/migrate.sh and is NEVER run by the pipeline — only by `demo/reset`.

DROP VIEW IF EXISTS app.v_users_by_source;
ALTER TABLE app.users DROP COLUMN IF EXISTS signup_source;

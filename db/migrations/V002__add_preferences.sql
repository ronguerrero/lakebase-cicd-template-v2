-- V002: Add a per-user preferences table.
--
-- Expand-only change: a brand-new table, no change to existing columns, so old and new
-- application code both keep working during the deployment window.

CREATE TABLE IF NOT EXISTS app.user_preferences (
    user_id    BIGINT NOT NULL REFERENCES app.users(user_id) ON DELETE CASCADE,
    pref_key   TEXT   NOT NULL,
    pref_value TEXT   NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, pref_key)
);

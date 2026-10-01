-- V003: Add a status column to users.
--
-- Expand step: the column is NOT NULL but carries a DEFAULT, so the ALTER is backward
-- compatible — existing rows get 'active' and existing readers that ignore the column
-- are unaffected. A CHECK constraint keeps the value set small and explicit.

ALTER TABLE app.users
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'suspended', 'closed'));

-- V001: Create the application schema and the core users table.
--
-- This is the initial baseline. Every environment database (app_qa_db, app_prod_db,
-- and any inherited DEV/PR branch) is built by replaying this file forward — never by
-- copying a branch. Keep migrations ordered and immutable once applied anywhere.

CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.users (
    user_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email        TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

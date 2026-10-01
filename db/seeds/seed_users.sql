-- Non-production sample data ONLY.
--
-- Seeds are applied to ephemeral DEV/PR branches and to the stable QA database for
-- validation. They are NEVER promoted to production: per the non-promotion rule, only
-- versioned code, immutable artifacts, and migration files move forward — not test rows.
-- Safe to re-run (idempotent upserts on the natural key).

INSERT INTO app.users (email, display_name, status) VALUES
    ('ada@example.com',    'Ada Lovelace',    'active'),
    ('grace@example.com',  'Grace Hopper',    'active'),
    ('alan@example.com',   'Alan Turing',     'suspended'),
    ('katherine@example.com', 'Katherine Johnson', 'active'),
    ('edsger@example.com', 'Edsger Dijkstra', 'closed')
ON CONFLICT (email) DO NOTHING;

INSERT INTO app.user_preferences (user_id, pref_key, pref_value)
SELECT u.user_id, 'theme', 'dark'
  FROM app.users u WHERE u.email = 'ada@example.com'
ON CONFLICT (user_id, pref_key) DO NOTHING;

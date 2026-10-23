CREATE TABLE IF NOT EXISTS demo_identity (
    identity text PRIMARY KEY,
    expires_at timestamptz NOT NULL,
    chats integer NOT NULL DEFAULT 0,
    thread_id text,
    submissions integer NOT NULL DEFAULT 0,
    deleting boolean NOT NULL DEFAULT false,
    run_ids jsonb NOT NULL DEFAULT '[]'::jsonb
);
CREATE TABLE IF NOT EXISTS demo_day (
    day date PRIMARY KEY,
    chats integer NOT NULL DEFAULT 0
);

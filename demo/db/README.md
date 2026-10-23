# Database deployment

Create the demo tables before starting the server. This directory is deployment input;
it is not part of the installed agent package or the backend runtime image.

From `demo/`, with `DATABASE_URL` set and the PostgreSQL client installed:

```sh
uv run --project .. --extra demo aegra db upgrade
psql "$DATABASE_URL" --set ON_ERROR_STOP=1 --single-transaction --file db/schema.sql
```

The SQL can be applied again without deleting data. Set `RUN_MIGRATIONS_ON_STARTUP=false`
in the server environment. The server only reads and updates existing demo tables.

Aegra 0.10.8 still runs LangGraph checkpoint/store setup at startup. It has no switch to
disable that setup. The flag above disables only Aegra's own schema migrations.

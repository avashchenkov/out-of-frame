# Integration checks with Docker Compose

These checks use the local Docker daemon. The runner creates a separate Compose project
for each run, with PostgreSQL 17 and Redis 7 on random ports bound to `127.0.0.1`.
Database files use container tmpfs mounts. No host directories, existing databases or
application secrets are mounted. Compose does not read `.env`.

Install project dependencies first with `uv sync --locked --extra demo`. The two images
must already exist locally. Downloading them is a separate, explicit action:

```sh
docker compose --env-file /dev/null --file demo/compose.test.yaml pull
```

From the repository root, run all committed integration checks:

```sh
uv run --no-env-file --offline --no-sync python tests/demo/run_integration.py
```

To select checks, pass pytest arguments:

```sh
uv run --no-env-file --offline --no-sync python tests/demo/run_integration.py \
  tests/demo/integration/test_queue.py -q
```

The runner starts services with `--pull never`, waits for health checks, passes their URLs
only to the test process, then removes its containers, network and volumes. Cleanup also runs
after test failure, startup failure, Ctrl+C or SIGTERM. It does not remove images or touch
other Compose projects. Tests use fake model/source calls; no paid API keys are required.

If the runner is forcibly killed, use the emergency cleanup command printed at startup.
The project name begins with `oof-test-`. Do not use global Docker prune commands.

Python tests and Aegra test processes run in the project's local environment. This file
configures test infrastructure only; backend image packaging and deployment are separate
roadmap work. Test code and database deployment input do not belong in the runtime image.

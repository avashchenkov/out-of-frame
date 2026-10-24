"""Run integration checks with disposable Compose services on the local Docker daemon."""

import os
import signal
import subprocess
import sys
from contextlib import contextmanager, suppress
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "demo/compose.test.yaml"


@contextmanager
def infrastructure():
    project = f"oof-test-{uuid4().hex[:12]}"
    compose = [
        "docker",
        "compose",
        "--env-file",
        os.devnull,
        "--file",
        str(COMPOSE),
        "--project-name",
        project,
    ]
    print(f"Using local Docker project {project}; images must already be available.", flush=True)
    print(
        f"Emergency cleanup: docker compose --env-file {os.devnull} "
        f"--file {COMPOSE} --project-name {project} down --volumes --remove-orphans",
        flush=True,
    )
    try:
        subprocess.run(
            [*compose, "up", "--wait", "--wait-timeout", "60", "--pull", "never"],
            check=True,
        )
        ports = {}
        for service, port in (("postgres", "5432"), ("redis", "6379")):
            address = subprocess.run(
                [*compose, "port", service, port],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            host, published = address.rsplit(":", 1)
            if host != "127.0.0.1" or not published.isdecimal():
                raise RuntimeError("Test services must be published only on IPv4 loopback")
            ports[service] = published
        yield {
            "OUT_OF_FRAME_TEST_DATABASE_URL": (
                f"postgresql://demo_test:local_test_only@127.0.0.1:{ports['postgres']}/demo_test"
            ),
            "OUT_OF_FRAME_TEST_REDIS_URL": f"redis://127.0.0.1:{ports['redis']}/0",
        }
    finally:
        subprocess.run(
            [*compose, "down", "--volumes", "--remove-orphans", "--timeout", "5"],
            check=True,
        )


def main():
    env = {
        key: value
        for key, value in os.environ.items()
        if not any(
            part in key
            for part in ("API_KEY", "LANGSMITH", "LANGCHAIN_TRACING", "OTEL", "ANTHROPIC", "TAVILY")
        )
    }
    try:
        with infrastructure() as urls:
            return run_tests(env | urls | {"LANGSMITH_TRACING": "false"})
    except KeyboardInterrupt:
        return 130
    except subprocess.CalledProcessError as error:
        return error.returncode


def run_tests(env):
    process = subprocess.Popen(
        [sys.executable, "-m", "pytest", *(sys.argv[1:] or ["tests/demo/integration"])],
        cwd=ROOT,
        env=env,
        start_new_session=True,
    )
    try:
        return process.wait()
    finally:
        # Stop pytest and any Aegra children before removing their database services.
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def interrupted(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupted)
    sys.exit(main())

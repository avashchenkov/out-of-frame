"""SDK + real Aegra processes, PostgreSQL and Redis; all external sources/models are fake.

Set OUT_OF_FRAME_TEST_DATABASE_URL and OUT_OF_FRAME_TEST_REDIS_URL to disposable local
services. These tests delete their demo records. They never load .env or use paid APIs.
"""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from langgraph_sdk import get_sync_client

ROOT = Path(__file__).parents[3]
DATABASE = os.environ.get("OUT_OF_FRAME_TEST_DATABASE_URL")
REDIS = os.environ.get("OUT_OF_FRAME_TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE or not REDIS, reason="needs disposable PostgreSQL and Redis"
)
SECRET = "local-integration-test-secret-at-least-32-chars"


@pytest.fixture
def server(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = json.loads((ROOT / "demo/aegra.json").read_text())
    config["graphs"]["agent"] = str(ROOT / "tests/demo/integration/fixture_graph.py") + ":graph"
    config_file = tmp_path / "aegra.json"
    config_file.write_text(json.dumps(config))
    env = {
        k: v
        for k, v in os.environ.items()
        if not any(s in k for s in ("API_KEY", "LANGSMITH", "OTEL", "ANTHROPIC", "TAVILY"))
    }
    env.update(
        {
            "AEGRA_CONFIG": str(config_file),
            "DATABASE_URL": DATABASE,
            "RUN_MIGRATIONS_ON_STARTUP": "false",
            "REDIS_URL": REDIS,
            "REDIS_BROKER_ENABLED": "true",
            "OUT_OF_FRAME_DEMO_PROXY_SECRET": SECRET,
            "LANGSMITH_TRACING": "false",
            "CRON_ENABLED": "false",
            "WORKER_COUNT": "1",
            "N_JOBS_PER_WORKER": "1",
            "LEASE_DURATION_SECONDS": "6",
            "HEARTBEAT_INTERVAL_SECONDS": "1",
            "REAPER_INTERVAL_SECONDS": "1",
            "OUT_OF_FRAME_DEMO_CLEANUP_SECONDS": "1",
            "OUT_OF_FRAME_DEMO_CANCEL_SECONDS": "0.5",
            "PYTHONPATH": str(ROOT),
            "OUT_OF_FRAME_TEST_PAUSE_FILE": str(tmp_path / "pause"),
            "OUT_OF_FRAME_TEST_FAIL_FILE": str(tmp_path / "fail"),
        }
    )
    process = None
    log = (tmp_path / "server.log").open("w")
    url = f"http://127.0.0.1:{port}"

    def stop(kill=False):
        nonlocal process
        if process and process.poll() is None:
            process.kill() if kill else process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def start():
        nonlocal process
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "aegra_api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-access-log",
            ],
            env=env,
            cwd=tmp_path,
            stdout=log,
            stderr=log,
        )
        for _ in range(200):
            if process.poll() is not None:
                pytest.fail((tmp_path / "server.log").read_text()[-10000:])
            try:
                if httpx.get(url + "/ready").status_code == 200:
                    return
            except httpx.ConnectError:
                pass
            time.sleep(0.1)
        pytest.fail("server did not start")

    import psycopg

    subprocess.run(
        [str(Path(sys.executable).with_name("aegra")), "db", "upgrade"],
        env=env,
        cwd=tmp_path,
        stdout=log,
        stderr=log,
        check=True,
    )
    with psycopg.connect(DATABASE) as connection:
        connection.execute((ROOT / "demo/db/schema.sql").read_text(encoding="utf-8"))
    with psycopg.connect(DATABASE, autocommit=True) as connection:
        for table in ("thread", "demo_identity", "demo_day"):
            if connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0]:
                connection.execute(f"TRUNCATE {table} CASCADE")
    try:
        start()
        yield url, start, stop, tmp_path
    finally:
        stop(kill=True)
        log.close()


def headers(identity):
    return {"x-demo-key": SECRET, "x-demo-identity": identity, "x-demo-csrf": "1"}


def wait_run(client, thread, run):
    for _ in range(200):
        saved = client.runs.get(thread, run)
        if saved["status"] not in ("pending", "running"):
            return saved
        time.sleep(0.1)
    pytest.fail("run did not finish")


def new(url, identity, text="Hello", replace=False):
    return httpx.post(
        url + "/demo/chat",
        headers=headers(identity),
        json={"text": text, "replace": replace},
        timeout=20,
    )


def test_restart_resume_and_private_access(server):
    from demo.backend.contract import run_request

    url, start, stop, _ = server
    visitor = str(uuid4())
    limits = httpx.get(url + "/demo/limits", headers={"x-demo-key": SECRET}).json()
    assert limits["daily_chats"] == 5 and limits["message_chars"] == 2000
    response = new(url, visitor)
    assert response.status_code == 200, response.text
    created = response.json()
    client = get_sync_client(url=url, headers=headers(visitor))
    thread, run = created["thread_id"], created["run_id"]
    assert wait_run(client, thread, run)["status"] == "interrupted"
    assert (
        httpx.get(f"{url}/threads/{thread}/state", headers=headers(str(uuid4()))).status_code == 404
    )
    stop()
    start()
    body = run_request(text="Freiheit 22, 13597 Berlin", resume=True)
    answer = httpx.post(f"{url}/threads/{thread}/runs", headers=headers(visitor), json=body)
    assert answer.status_code == 200, answer.text
    assert wait_run(client, thread, answer.json()["run_id"])["status"] == "success"
    state = client.threads.get_state(thread)
    messages = state["values"]["messages"]
    assert messages[-1]["id"] == "final-report"
    assert messages[-1]["content"] == state["values"]["report"]
    assert sum(m["id"] == "final-report" for m in messages) == 1
    assert not state["next"] and not state["interrupts"]
    assert (
        httpx.post(f"{url}/threads/{thread}/runs", headers=headers(visitor), json=body).status_code
        == 409
    )
    assert httpx.delete(url + "/demo/chat", headers=headers(visitor)).status_code == 200
    assert httpx.get(f"{url}/threads/{thread}/state", headers=headers(visitor)).status_code == 404
    remaining = httpx.get(url + "/demo/session", headers=headers(visitor)).json()
    assert remaining["chats_remaining"] == 1
    assert remaining["thread_id"] is None


def test_input_limits_and_execution_overrides(server):
    from demo.backend.contract import run_request

    url, _, _, _ = server
    visitor = str(uuid4())
    assert new(url, visitor, "x" * 2001).status_code == 422
    made = new(url, visitor).json()
    client = get_sync_client(url=url, headers=headers(visitor))
    thread = made["thread_id"]
    wait_run(client, thread, made["run_id"])
    for path, method in (
        (f"/threads/{thread}/history", "GET"),
        ("/threads", "POST"),
        ("/runs", "POST"),
        ("/demo/cleanup", "POST"),
        (f"/threads/{thread}/state", "POST"),
    ):
        assert httpx.request(method, url + path, headers=headers(visitor)).status_code == 403
    assert httpx.get(url + "/demo/session", headers={"x-demo-identity": visitor}).status_code == 401
    body = run_request(text="Please wait", resume=True)
    for override in (
        {"context": {"date": "2000-01-01"}},
        {"config": {"configurable": {"thread_id": "other"}}},
        {"stream_subgraphs": True},
        {"durability": "exit"},
        {"command": {"resume": "Wait", "update": {"report": "forged"}}},
    ):
        response = httpx.post(
            f"{url}/threads/{thread}/runs", headers=headers(visitor), json=body | override
        )
        assert response.status_code == 422, response.text
    for _ in range(6):
        response = httpx.post(f"{url}/threads/{thread}/runs", headers=headers(visitor), json=body)
        assert response.status_code == 200, response.text
        assert wait_run(client, thread, response.json()["run_id"])["status"] == "interrupted"
    response = httpx.post(f"{url}/threads/{thread}/runs", headers=headers(visitor), json=body)
    assert response.status_code == 429
    assert (
        httpx.get(url + "/demo/session", headers=headers(visitor)).json()["submissions_remaining"]
        == 0
    )
    assert client.threads.get_state(thread)["values"]["messages"]
    assert httpx.delete(url + "/demo/chat", headers=headers(visitor)).status_code == 200


def test_the_last_submission_can_finish_and_replacement_keeps_expiry(server):
    from demo.backend.contract import run_request

    url, _, _, _ = server
    visitor = str(uuid4())
    made = new(url, visitor).json()
    client = get_sync_client(url=url, headers=headers(visitor))
    thread = made["thread_id"]
    wait_run(client, thread, made["run_id"])
    for message in ["Please wait"] * 5 + ["Freiheit 22, 13597 Berlin"]:
        response = httpx.post(
            f"{url}/threads/{thread}/runs",
            headers=headers(visitor),
            json=run_request(text=message, resume=True),
        )
        assert response.status_code == 200, response.text
        result = wait_run(client, thread, response.json()["run_id"])
    assert result["status"] == "success"
    replaced = new(url, visitor, replace=True)
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["expires_at"] == made["expires_at"]
    assert replaced.json()["thread_id"] != thread
    assert httpx.get(f"{url}/threads/{thread}/state", headers=headers(visitor)).status_code == 404
    assert new(url, visitor, replace=True).status_code == 429
    assert httpx.delete(url + "/demo/chat", headers=headers(visitor)).status_code == 200
    assert new(url, visitor).status_code == 429


def test_concurrent_global_admission_survives_restart(server):
    from concurrent.futures import ThreadPoolExecutor

    url, start, stop, _ = server
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: new(url, str(uuid4())), range(6)))
    assert sorted(r.status_code for r in responses) == [200] * 5 + [429]
    refused = next(r for r in responses if r.status_code == 429)
    assert "cookie" not in refused.json() and "set-cookie" not in refused.headers
    stop()
    start()
    assert new(url, str(uuid4())).status_code == 429


def test_busy_service_queues_without_resubmission_and_allows_queued_deletion(server):
    url, _, _, folder = server
    first, second, removed = (str(uuid4()) for _ in range(3))
    (folder / "pause").touch()
    active = new(url, first, "Freiheit 22, 13597 Berlin").json()
    wait_for_file(folder / "pause.started")
    queued = new(url, second).json()
    deleted = new(url, removed).json()
    client = get_sync_client(url=url, headers=headers(second))
    run = client.runs.get(queued["thread_id"], queued["run_id"])
    assert run["status"] == "pending"
    before = httpx.get(url + "/demo/session", headers=headers(second)).json()
    assert before["status"] == "pending" and before["submissions_remaining"] == 6
    assert httpx.delete(url + "/demo/chat", headers=headers(removed)).status_code == 200
    assert (
        httpx.get(
            f"{url}/threads/{deleted['thread_id']}/state", headers=headers(removed)
        ).status_code
        == 404
    )
    (folder / "pause").unlink()
    first_client = get_sync_client(url=url, headers=headers(first))
    assert wait_run(first_client, active["thread_id"], active["run_id"])["status"] == "success"
    assert wait_run(client, queued["thread_id"], queued["run_id"])["status"] == "interrupted"
    after = httpx.get(url + "/demo/session", headers=headers(second)).json()
    assert after["submissions_remaining"] == before["submissions_remaining"]
    assert after["chats_remaining"] == before["chats_remaining"]


def wait_for_file(path):
    for _ in range(200):
        if path.exists():
            return
        time.sleep(0.05)
    pytest.fail("research did not start")


def test_worker_crash_recovers_without_a_new_submission(server):
    url, start, stop, folder = server
    visitor = str(uuid4())
    (folder / "pause").touch()
    made = new(url, visitor, "Freiheit 22, 13597 Berlin").json()
    wait_for_file(folder / "pause.started")
    stop(kill=True)
    (folder / "pause").unlink()
    start()
    client = get_sync_client(url=url, headers=headers(visitor))
    result = wait_run(client, made["thread_id"], made["run_id"])
    assert result["status"] == "success", result
    assert (
        httpx.get(url + "/demo/session", headers=headers(visitor)).json()["submissions_remaining"]
        == 6
    )
    messages = client.threads.get_state(made["thread_id"])["values"]["messages"]
    assert sum(m["id"] == "final-report" for m in messages) == 1
    assert sum(m["type"] == "human" for m in messages) == 1


def test_deleting_a_running_chat_frees_the_queue_then_clears_postgres_and_redis(server):
    import psycopg
    from redis import Redis

    url, _, _, folder = server
    visitor, waiting = str(uuid4()), str(uuid4())
    (folder / "pause").touch()
    made = new(url, visitor, "Freiheit 22, 13597 Berlin").json()
    wait_for_file(folder / "pause.started")
    queued = new(url, waiting).json()
    queued_client = get_sync_client(url=url, headers=headers(waiting))
    assert queued_client.runs.get(queued["thread_id"], queued["run_id"])["status"] == "pending"
    response = httpx.delete(url + "/demo/chat", headers=headers(visitor))
    assert response.status_code == 409 and "deletion_pending" in response.text
    assert (
        httpx.get(f"{url}/threads/{made['thread_id']}/state", headers=headers(visitor)).status_code
        == 404
    )
    # The cancelled run frees the only worker slot while its synchronous node still runs.
    queued_run = wait_run(queued_client, queued["thread_id"], queued["run_id"])
    assert queued_run["status"] == "interrupted"
    assert (folder / "pause").exists()
    (folder / "pause").unlink()
    for _ in range(100):
        info = httpx.get(url + "/demo/session", headers=headers(visitor)).json()
        if not info["deleting"]:
            break
        time.sleep(0.1)
    assert not info["deleting"] and info["thread_id"] is None
    assert info["chats_remaining"] == 1
    with psycopg.connect(DATABASE) as conn:
        for table in ("thread", "runs", "checkpoints", "checkpoint_writes", "checkpoint_blobs"):
            assert (
                conn.execute(
                    f"SELECT count(*) FROM {table} WHERE thread_id=%s", (made["thread_id"],)
                ).fetchone()[0]
                == 0
            )
    redis = Redis.from_url(REDIS)
    assert not list(redis.scan_iter(f"*{made['run_id']}*"))


def test_expiry_is_inaccessible_and_native_ttl_prunes_after_restart(server):
    import psycopg

    url, start, stop, _ = server
    visitor = str(uuid4())
    made = new(url, visitor).json()
    client = get_sync_client(url=url, headers=headers(visitor))
    wait_run(client, made["thread_id"], made["run_id"])
    stop()
    with psycopg.connect(DATABASE, autocommit=True) as conn:
        conn.execute(
            "UPDATE demo_identity SET expires_at=now()-interval '1 second' WHERE identity=%s",
            (visitor,),
        )
        conn.execute(
            "UPDATE thread_ttl SET expires_at=now()-interval '1 second' WHERE thread_id=%s",
            (made["thread_id"],),
        )
    start()
    assert (
        httpx.get(f"{url}/threads/{made['thread_id']}/state", headers=headers(visitor)).status_code
        == 404
    )
    with psycopg.connect(DATABASE) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM thread WHERE thread_id=%s", (made["thread_id"],)
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM demo_identity WHERE identity=%s", (visitor,)
            ).fetchone()[0]
            == 0
        )


def test_manual_retry_uses_latest_checkpoint_and_consumes_a_submission(server):
    url, _, _, folder = server
    visitor = str(uuid4())
    (folder / "fail").touch()
    made = new(url, visitor, "Freiheit 22, 13597 Berlin").json()
    client = get_sync_client(url=url, headers=headers(visitor))
    assert wait_run(client, made["thread_id"], made["run_id"])["status"] == "error"
    response = httpx.post(url + "/demo/retry", headers=headers(visitor))
    assert response.status_code == 200, response.text
    assert wait_run(client, made["thread_id"], response.json()["run_id"])["status"] == "success"
    info = httpx.get(url + "/demo/session", headers=headers(visitor)).json()
    assert info["submissions_remaining"] == 5 and info["complete"]
    assert "PRIVATE_ERROR_PAYLOAD" not in (folder / "server.log").read_text()


def test_disconnect_does_not_cancel_research(server):
    url, _, _, folder = server
    visitor = str(uuid4())
    (folder / "pause").touch()
    made = new(url, visitor, "Freiheit 22, 13597 Berlin").json()
    wait_for_file(folder / "pause.started")
    endpoint = f"{url}/threads/{made['thread_id']}/runs/{made['run_id']}/stream"
    with httpx.stream("GET", endpoint, headers=headers(visitor)) as stream:
        assert stream.status_code == 200
        for line in stream.iter_lines():
            if line:
                break
    (folder / "pause").unlink()
    client = get_sync_client(url=url, headers=headers(visitor))
    assert wait_run(client, made["thread_id"], made["run_id"])["status"] == "success"


def test_two_tabs_cannot_create_two_current_chats(server):
    from concurrent.futures import ThreadPoolExecutor

    url, _, _, _ = server
    visitor = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: new(url, visitor), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    info = httpx.get(url + "/demo/session", headers=headers(visitor)).json()
    assert info["chats_remaining"] == 1 and info["submissions_remaining"] == 6

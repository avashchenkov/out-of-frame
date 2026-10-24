"""Runner failures must still clean only their own Compose project; no Docker calls."""

import os
import signal
import subprocess
import sys
from unittest.mock import Mock

import pytest
import yaml

from tests.demo import run_integration as runner


@pytest.mark.parametrize("failure", [None, "startup", "tests", "interrupt", "cleanup"])
def test_runner_cleans_its_project_and_preserves_failure(monkeypatch, failure):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if "up" in command and failure == "startup":
            raise subprocess.CalledProcessError(7, command)
        if "port" in command:
            return subprocess.CompletedProcess(command, 0, stdout="127.0.0.1:54321\n")
        if "down" in command and failure == "cleanup":
            raise subprocess.CalledProcessError(9, command)
        return subprocess.CompletedProcess(command, 0)

    def run_tests(env):
        calls.append(([sys.executable, "-m", "pytest", "tests/demo/integration"], {"env": env}))
        if failure == "interrupt":
            raise KeyboardInterrupt
        return 3 if failure == "tests" else 0

    monkeypatch.setattr(runner.subprocess, "run", run)
    monkeypatch.setattr(runner, "run_tests", run_tests)
    monkeypatch.setattr(sys, "argv", ["run_integration.py"])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-reach-tests")
    monkeypatch.setenv("OUT_OF_FRAME_TEST_DATABASE_URL", "must-not-use-existing-db")
    expected = {None: 0, "startup": 7, "tests": 3, "interrupt": 130, "cleanup": 9}
    assert runner.main() == expected[failure]
    commands = [command for command, _ in calls]
    up, down = commands[0], commands[-1]
    project = up[up.index("--project-name") + 1]
    assert project.startswith("oof-test-")
    assert down[down.index("--project-name") + 1] == project
    assert "--volumes" in down and "--remove-orphans" in down and "down" in down
    assert up[up.index("--pull") + 1] == "never"
    assert up[up.index("--env-file") + 1] == os.devnull
    if failure != "startup":
        command, options = next((c, o) for c, o in calls if "pytest" in c)
        assert command[-1] == "tests/demo/integration"
        assert "ANTHROPIC_API_KEY" not in options["env"]
        assert "127.0.0.1:54321/demo_test" in options["env"]["OUT_OF_FRAME_TEST_DATABASE_URL"]


@pytest.mark.parametrize("failure", [False, True])
def test_runner_stops_test_process_group_before_returning(monkeypatch, failure):
    process = Mock(pid=12345)
    process.wait.side_effect = [KeyboardInterrupt() if failure else 0, None, None]
    popen, kill = Mock(return_value=process), Mock()
    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    monkeypatch.setattr(runner.os, "killpg", kill)
    monkeypatch.setattr(sys, "argv", ["run_integration.py", "tests/demo/integration/test_queue.py"])
    if failure:
        with pytest.raises(KeyboardInterrupt):
            runner.run_tests({})
    else:
        assert runner.run_tests({}) == 0
    assert popen.call_args.kwargs["start_new_session"] is True
    assert popen.call_args.args[0][-1] == "tests/demo/integration/test_queue.py"
    assert kill.call_args_list == [((12345, signal.SIGTERM),), ((12345, signal.SIGKILL),)]


def test_compose_has_only_disposable_loopback_services():
    services = yaml.safe_load(runner.COMPOSE.read_text())["services"]
    assert set(services) == {"postgres", "redis"}
    for service in services.values():
        assert all(port.startswith("127.0.0.1::") for port in service["ports"])
        assert service["tmpfs"]
        assert "volumes" not in service and "env_file" not in service
    assert services["postgres"]["tmpfs"] == ["/var/lib/postgresql/data"]
    assert services["redis"]["tmpfs"] == ["/data"]

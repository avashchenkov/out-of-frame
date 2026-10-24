"""Service startup and shutdown without model, source or database calls."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from demo.backend import activity, auth, config, lifecycle
from out_of_frame.agent import ObjectToInvestigate
from out_of_frame.state import Address, Coordinates, MapObject


@pytest.fixture
def service(monkeypatch):
    for prefix in ("LANGSMITH", "LANGCHAIN"):
        for suffix in ("TRACING", "TRACING_V2"):
            monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)
    settings = SimpleNamespace(
        observability=SimpleNamespace(OTEL_TARGETS="", OTEL_CONSOLE_EXPORT=False),
        db=SimpleNamespace(DB_ECHO_LOG=False),
        redis=SimpleNamespace(REDIS_BROKER_ENABLED=True),
    )
    monkeypatch.setattr(lifecycle, "settings", settings)
    monkeypatch.setattr(config, "DEMO_PROXY_SECRET", "test-secret-with-at-least-32-characters")
    monkeypatch.setattr(lifecycle, "get_auth_instance", lambda: auth.auth)
    monkeypatch.setattr(lifecycle, "get_thread_ttl_config", lambda: None)
    monkeypatch.setattr(lifecycle.private_logging, "install", Mock())
    ready = asyncio.Event()
    monkeypatch.setattr(activity, "startup_cleanup_finished", ready)
    connection = SimpleNamespace(scalar=AsyncMock(return_value=True), commit=AsyncMock())
    connection.execute = AsyncMock()

    @asynccontextmanager
    async def connect():
        yield connection

    checkpointer = SimpleNamespace(serde=None)
    engine = SimpleNamespace(connect=Mock(side_effect=connect))
    monkeypatch.setattr(
        lifecycle,
        "db_manager",
        SimpleNamespace(engine=engine, get_checkpointer=lambda: checkpointer),
    )
    sweep, stop = AsyncMock(), AsyncMock()
    monkeypatch.setattr(lifecycle.cleanup, "sweep", sweep)
    monkeypatch.setattr(lifecycle, "executor", SimpleNamespace(stop=stop))
    return SimpleNamespace(
        settings=settings,
        connection=connection,
        engine=engine,
        ready=ready,
        sweep=sweep,
        stop=stop,
        checkpointer=checkpointer,
    )


@pytest.mark.parametrize(
    "invalid",
    ["secret", "auth", "sql_logging", "redis", "ttl", "limit", "tracing"],
)
def test_invalid_settings_fail_before_database_access(service, monkeypatch, invalid):
    match invalid:
        case "secret":
            monkeypatch.setattr(config, "DEMO_PROXY_SECRET", "short")
        case "auth":
            monkeypatch.setattr(lifecycle, "get_auth_instance", lambda: None)
        case "sql_logging":
            service.settings.db.DB_ECHO_LOG = True
        case "redis":
            service.settings.redis.REDIS_BROKER_ENABLED = False
        case "ttl":
            monkeypatch.setattr(lifecycle, "get_thread_ttl_config", lambda: {})
        case "limit":
            monkeypatch.setattr(config, "DEMO_SUBMISSIONS", 0)
        case "tracing":
            monkeypatch.setenv("LANGSMITH_TRACING", "true")

    async def scenario():
        with pytest.raises(RuntimeError):
            async with lifecycle.lifespan(None):
                pytest.fail("invalid configuration reached readiness")

    asyncio.run(scenario())
    service.engine.connect.assert_not_called()
    service.sweep.assert_not_awaited()


@pytest.mark.parametrize(
    "tracing",
    [
        "otel",
        "console",
        "LANGSMITH_TRACING",
        "LANGSMITH_TRACING_V2",
        "LANGCHAIN_TRACING",
        "LANGCHAIN_TRACING_V2",
    ],
)
def test_external_tracing_rejected_before_instrumentation(service, monkeypatch, tracing):
    if tracing == "otel":
        service.settings.observability.OTEL_TARGETS = "PHOENIX"
    elif tracing == "console":
        service.settings.observability.OTEL_CONSOLE_EXPORT = True
    else:
        monkeypatch.setenv(tracing, "true")
        # Check the SDK's own switch, without creating a client or sending anything.
        from langsmith import utils

        utils.get_env_var.cache_clear()
        try:
            assert utils.tracing_is_enabled()
        finally:
            utils.get_env_var.cache_clear()
    with pytest.raises(RuntimeError, match="External tracing"):
        lifecycle.reject_external_tracing()


def test_second_process_cannot_start_cleanup_or_unlock_another_owner(service):
    service.connection.scalar.return_value = False

    async def scenario():
        with pytest.raises(RuntimeError, match="Only one"):
            async with lifecycle.lifespan(None):
                pytest.fail("second process started")

    asyncio.run(scenario())
    service.sweep.assert_not_awaited()
    service.connection.execute.assert_not_awaited()
    assert not service.ready.is_set()


@pytest.mark.parametrize("startup_failure", [False, True])
def test_cleanup_gates_readiness_and_releases_lock_after_stopping_work(service, startup_failure):
    async def sweep():
        assert not service.ready.is_set()
        if startup_failure:
            raise RuntimeError("cleanup unavailable")

    async def stop():
        assert not service.ready.is_set()
        service.connection.execute.assert_not_awaited()

    service.sweep.side_effect = sweep
    service.stop.side_effect = stop

    async def scenario():
        try:
            async with lifecycle.lifespan(None):
                assert service.ready.is_set()
                service.connection.execute.assert_not_awaited()
        except RuntimeError as error:
            assert startup_failure and str(error) == "cleanup unavailable"
        else:
            assert not startup_failure

    asyncio.run(scenario())
    service.stop.assert_awaited_once()
    service.connection.execute.assert_awaited_once()
    assert "pg_advisory_unlock" in str(service.connection.execute.call_args.args[0])
    assert not service.ready.is_set()
    # Real serializer: nested agent records must survive checkpoints as their own types.
    item = ObjectToInvestigate(
        map_object=MapObject(
            id="map-1",
            name=None,
            details={},
            addresses=[],
            coordinates=Coordinates(lat=52.5, lon=13.4),
            distance_from_property_m=10,
            source_id="source-1",
        ),
        source_kind="map",
    )
    values = {"property": Address(text="Berlin"), "pending": item}
    serde = service.checkpointer.serde
    assert serde.loads_typed(serde.dumps_typed(values)) == values


def test_shutdown_keeps_lock_until_cancelled_sync_node_finishes(service, monkeypatch):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        def active():
            entered.set()
            return not release.is_set()

        monkeypatch.setattr(activity, "has_active_nodes", active)
        context = lifecycle.lifespan(None)
        await context.__aenter__()
        closing = asyncio.create_task(context.__aexit__(None, None, None))
        await entered.wait()
        assert not closing.done()
        service.connection.execute.assert_not_awaited()
        release.set()
        await asyncio.wait_for(closing, 1)
        service.connection.execute.assert_awaited_once()

    asyncio.run(scenario())


def test_periodic_cleanup_retries_without_logging_private_errors(service, monkeypatch, caplog):
    service.sweep.side_effect = [RuntimeError("private address"), None]

    async def sleep(_):
        if service.sweep.await_count == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(lifecycle.asyncio, "sleep", sleep)

    async def scenario():
        with pytest.raises(asyncio.CancelledError):
            await lifecycle.periodic()

    asyncio.run(scenario())
    assert service.sweep.await_count == 2
    assert "pending records will be retried" in caplog.text
    assert "private address" not in caplog.text

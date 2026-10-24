"""The browser can attach to the current run without submitting another one."""

import asyncio
import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aegra_api.models import User

from demo.backend import app, auth, storage


@pytest.mark.parametrize("deleting", [False, True])
def test_session_exposes_only_the_current_chat_run(monkeypatch, deleting):
    monkeypatch.setattr(
        storage,
        "identity_row",
        AsyncMock(
            return_value={
                "thread_id": "current-thread",
                "deleting": deleting,
                "expires_at": dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
                "chats": 1,
                "submissions": 1,
            }
        ),
    )
    latest = AsyncMock(return_value=SimpleNamespace(run_id="current-run", status="pending"))
    monkeypatch.setattr(auth, "latest_run", latest)
    monkeypatch.setattr(auth, "snapshot_for", AsyncMock(return_value=SimpleNamespace()))
    result = asyncio.run(app.session_info(User(identity="owner")))
    assert result["run_id"] == (None if deleting else "current-run")
    if deleting:
        latest.assert_not_awaited()
    else:
        latest.assert_awaited_once_with("current-thread")
        assert result["status"] == "pending" and not result["complete"]

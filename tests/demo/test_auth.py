"""Private identity and ownership checks without a database or external calls."""

import asyncio
import datetime as dt
from uuid import uuid4

import pytest
from fastapi import HTTPException

from demo.backend import auth, config, storage


def test_only_the_trusted_proxy_can_assert_an_identity(monkeypatch):
    monkeypatch.setattr(config, "DEMO_PROXY_SECRET", "a" * 32)
    identity = str(uuid4())
    headers = {"X-Demo-Key": "a" * 32, "X-Demo-Identity": identity}
    result = asyncio.run(auth.authenticate(headers))
    assert result["identity"] == identity and result["is_authenticated"]
    for invalid in (
        {},
        {"x-demo-identity": identity},
        {"x-demo-key": "wrong", "x-demo-identity": identity},
        {"x-demo-key": "a" * 32, "x-demo-identity": "not-a-uuid"},
    ):
        with pytest.raises(HTTPException) as error:
            asyncio.run(auth.authenticate(invalid))
        assert error.value.status_code == 401


@pytest.mark.parametrize(
    "override",
    [
        None,
        {"thread_id": "another-chat"},
        {"deleting": True},
        {"expires_at": dt.datetime(2000, 1, 1, tzinfo=dt.UTC)},
    ],
)
def test_missing_foreign_deleting_and_expired_chats_are_hidden(monkeypatch, override):
    row = {
        "thread_id": "current-chat",
        "deleting": False,
        "expires_at": dt.datetime(2099, 1, 1, tzinfo=dt.UTC),
    }

    async def lookup(identity):
        assert identity == "owner"
        return None if override is None else row | override

    monkeypatch.setattr(storage, "identity_row", lookup)
    with pytest.raises(HTTPException) as error:
        asyncio.run(auth.owned("owner", "current-chat"))
    assert error.value.status_code == 404


def test_the_owner_can_access_the_current_unexpired_chat(monkeypatch):
    row = {
        "thread_id": "current-chat",
        "deleting": False,
        "expires_at": dt.datetime(2099, 1, 1, tzinfo=dt.UTC),
    }

    async def lookup(identity):
        assert identity == "owner"
        return row

    monkeypatch.setattr(storage, "identity_row", lookup)
    assert asyncio.run(auth.owned("owner", "current-chat")) == row

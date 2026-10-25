"""Private boundary checks: the signed identity, completed reports and fixed execution
parameters."""

import hashlib
import hmac
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage

from demo.backend import config, contract


def test_identity_is_signed_with_the_proxy_secret(monkeypatch):
    monkeypatch.setattr(config, "DEMO_PROXY_SECRET", "a" * 32)
    identity = str(uuid4())
    token = contract.sign_identity(identity, 2000)
    payload, signature = token.rsplit(".", 1)
    assert payload == f"{identity}.2000"
    assert hmac.compare_digest(
        signature, hmac.new(b"a" * 32, payload.encode(), hashlib.sha256).hexdigest()
    )
    with pytest.raises(ValueError):
        contract.sign_identity("not-a-uuid", 2000)


def test_a_draft_or_idle_thread_is_not_a_completed_report():
    snapshot = SimpleNamespace(next=(), interrupts=(), values={"report": "draft", "messages": []})
    assert not contract.completed("success", snapshot)
    snapshot.values["messages"] = [AIMessage("report", id="final-report")]
    assert not contract.completed("error", snapshot)
    assert contract.completed("success", snapshot)
    snapshot.next = ("wait_for_answer",)
    assert not contract.completed("success", snapshot)


def test_messages_and_answers_match_the_aegra_request_schema():
    from aegra_api.models import RunCreate

    first = RunCreate(**contract.run_request(text="Hello")).model_dump()
    answer = RunCreate(**contract.run_request(text="Berlin", resume=True)).model_dump()
    assert first["input"]["messages"] == [{"type": "human", "content": "Hello"}]
    assert first["command"] is None
    assert answer["command"]["resume"] == "Berlin"
    assert answer["input"] is None
    for text in (None, "", " ", 123, "a" * (config.DEMO_MESSAGE_CHARS + 1)):
        with pytest.raises(HTTPException):
            contract.run_request(text=text)


def test_client_execution_settings_are_rejected():
    from aegra_api.models import RunCreate

    from demo.backend import auth

    body = contract.run_request(text="Hello")
    auth.validate_run(RunCreate(**body).model_dump())
    auth.validate_run(RunCreate(**contract.run_request(text="Answer", resume=True)).model_dump())
    for key, value in (
        ("context", {"date": "yesterday"}),
        ("checkpoint_id", str(uuid4())),
        ("interrupt_after", "*"),
        ("stream_subgraphs", True),
        ("durability", "exit"),
        ("assistant_id", "other"),
    ):
        with pytest.raises(HTTPException):
            auth.validate_run(RunCreate(**(body | {key: value})).model_dump())

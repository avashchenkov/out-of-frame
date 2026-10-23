"""Private boundary checks: identities, safe projections and fixed execution parameters."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage

from out_of_frame import config
from out_of_frame.demo import contract

MARKER = "PRIVATE_SOURCE_TEXT_MUST_NOT_REACH_THE_BROWSER"


def test_cookie_signature_and_fixed_expiry(monkeypatch):
    monkeypatch.setattr(config, "DEMO_PROXY_SECRET", "a" * 32)
    monkeypatch.setattr(contract.time, "time", lambda: 1000)
    identity = str(uuid4())
    token = contract.sign_identity(identity, 2000)
    assert contract.read_identity(token) == (identity, 2000)
    for forged in (
        token[:-1],
        token.replace("2000", "3000"),
        token.replace(identity, str(uuid4())),
    ):
        with pytest.raises(HTTPException):
            contract.read_identity(forged)
    monkeypatch.setattr(contract.time, "time", lambda: 2000)
    with pytest.raises(HTTPException):
        contract.read_identity(token)
    assert contract.COOKIE_OPTIONS == {
        "httponly": True,
        "secure": True,
        "samesite": "lax",
        "path": "/",
    }


def test_all_exposed_response_shapes_drop_internal_data():
    values = {
        "messages": [
            AIMessage("Question?", id="question", additional_kwargs={"source": MARKER}),
            {"type": "tool", "content": MARKER},
        ],
        "sources": [{"content": MARKER}],
        "report": MARKER,
        "findings": [{"key_facts": [MARKER]}],
        "failures": ["map"],
    }
    envelopes = [contract.visible_values(values)]
    envelopes += [contract.visible_event("values", values)] * 2  # live and replay
    envelopes += [contract.visible_event("updates", {"write_report": {"report": MARKER}})]
    envelopes += [contract.visible_event("error", {"message": MARKER})]
    envelopes += [
        contract.visible_read(
            "state",
            {
                "values": values,
                "tasks": [MARKER],
                "interrupts": [{"id": "q", "value": "Question?", "extra": MARKER}],
            },
        )
    ]
    for kind in ("thread", "run"):
        envelopes.append(
            contract.visible_read(
                kind,
                {
                    "output": values,
                    "input": MARKER,
                    "metadata": MARKER,
                    "error_message": MARKER,
                    "status": "success",
                },
            )
        )
    assert MARKER not in json.dumps(envelopes)
    assert "Question?" in json.dumps(envelopes) and "map" in json.dumps(envelopes)
    assert contract.visible_event("messages/partial", {"content": MARKER}) is None
    with pytest.raises(ValueError):
        contract.visible_read("history", {"values": values})


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

    from out_of_frame.demo import auth

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

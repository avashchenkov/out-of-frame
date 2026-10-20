"""The chat model that every model call is built on, and the settings that each call gets."""

from out_of_frame import (
    chat_model,
    conversation,
    finding,
    investigation,
    prompt_injection,
    report,
    triage,
)
from out_of_frame.chat_model import build_chat_model
from out_of_frame.config import EFFORT, MAX_TOKENS, MODEL


def test_an_effort_goes_to_the_api_unless_it_is_the_default():
    assert build_chat_model("m", "xhigh").output_config == {"effort": "xhigh"}
    assert build_chat_model("m", "default").output_config is None


def test_the_model_gets_its_output_tokens():
    assert build_chat_model("m", "default", 1234).max_tokens == 1234


def test_the_injection_check_has_its_own_settings_and_every_other_call_the_agents(monkeypatch):
    builders = {
        "extract": (conversation, conversation.build_extract_model),
        "ask": (conversation, conversation.build_ask_model),
        "triage": (triage, triage.build_triage_model),
        "search": (investigation, investigation.build_search_model),
        "finding": (finding, finding.build_finding_model),
        "report": (report, report.build_report_model),
        "injection check": (prompt_injection, prompt_injection.build_check_model),
    }
    # Settings of its own, apart from the agent's whatever the defaults, so that a swap shows.
    monkeypatch.setattr(prompt_injection, "INJECTION_MODEL", "an injection model")
    monkeypatch.setattr(prompt_injection, "INJECTION_EFFORT", "an injection effort")
    monkeypatch.setattr(prompt_injection, "INJECTION_MAX_TOKENS", 1234)
    built = {}
    for name, (module, builder) in builders.items():

        def build(model=MODEL, effort=EFFORT, max_tokens=MAX_TOKENS, name=name):
            built[name] = (model, effort, max_tokens)
            return chat_model.build_chat_model(model, effort, max_tokens)

        monkeypatch.setattr(module, "build_chat_model", build)
        builder.cache_clear()
        builder()
        builder.cache_clear()  # so that no later test gets this model
    agent = {name: (MODEL, EFFORT, MAX_TOKENS) for name in builders if name != "injection check"}
    injection = ("an injection model", "an injection effort", 1234)
    assert built == agent | {"injection check": injection}

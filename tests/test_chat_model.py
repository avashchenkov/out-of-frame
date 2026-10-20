"""The chat model that every model call is built on, and the settings that each call gets."""

import functools

from langchain_anthropic import ChatAnthropic

from evals.graders import judges
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


def test_each_call_gets_the_settings_of_its_role(monkeypatch):
    """The settings of the models that the builders really build: the agent's for every call but
    the injection check's and the judges', which get their own, set apart from the agent's here
    whatever the defaults, so that a swap shows."""
    monkeypatch.setattr(prompt_injection, "INJECTION_MODEL", "an injection model")
    monkeypatch.setattr(prompt_injection, "INJECTION_EFFORT", "an injection effort")
    monkeypatch.setattr(prompt_injection, "INJECTION_MAX_TOKENS", 1234)
    monkeypatch.setattr(judges, "JUDGE_MODEL", "a judge model")
    monkeypatch.setattr(judges, "JUDGE_EFFORT", "a judge effort")
    monkeypatch.setattr(judges, "JUDGE_MAX_TOKENS", 5678)
    built = []

    def record(**kwargs) -> ChatAnthropic:
        built.append(ChatAnthropic(**kwargs))
        return built[-1]

    monkeypatch.setattr(chat_model, "ChatAnthropic", record)
    builders = {
        "extract": conversation.build_extract_model,
        "ask": conversation.build_ask_model,
        "triage": triage.build_triage_model,
        "search": investigation.build_search_model,
        "finding": finding.build_finding_model,
        "report": report.build_report_model,
        "injection check": prompt_injection.build_check_model,
        "judge": judges.build_judge_model,
    }
    settings = {}
    for name, builder in builders.items():
        build = functools.partial(builder, judges.SupportGrade) if name == "judge" else builder
        builder.cache_clear()
        build()
        builder.cache_clear()  # so that no later test gets this model
        settings[name] = (built[-1].model, built[-1].output_config, built[-1].max_tokens)
    agent = (MODEL, None if EFFORT == "default" else {"effort": EFFORT}, MAX_TOKENS)
    assert settings == {name: agent for name in list(builders)[:6]} | {
        "injection check": ("an injection model", {"effort": "an injection effort"}, 1234),
        "judge": ("a judge model", {"effort": "a judge effort"}, 5678),
    }

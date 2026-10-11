"""The LLM judges with a stubbed model: how the draft is split, what each judge gets, and how
its answer is read."""

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from evals.graders import judges
from evals.graders.judges import (
    InterpretationGrade,
    JudgeError,
    NoVerdictGrade,
    QuestionAnswer,
    Statement,
    SupportGrade,
    combine,
    judge_interpretation,
    judge_no_verdict,
    judge_support,
    split_into_statements,
)
from out_of_frame.state import Address, Finding, RunState
from tests.test_report import DATE, MAP, PAGE, SITE, STATE

SUPPORTED = SupportGrade(reason="The page says so.", grade="supported")
YES = QuestionAnswer(reason="It does.", answer="yes")
INTERPRETED = InterpretationGrade(
    explains_meaning=YES, lists_unclear_objects=YES, tells_failures=YES, fits_type=YES
)


def answer(parsed, stop_reason="end_turn", parsing_error=None) -> dict:
    """An answer as with_structured_output(include_raw=True) gives it."""
    raw = AIMessage("", response_metadata={"stop_reason": stop_reason})
    return {"raw": raw, "parsed": parsed, "parsing_error": parsing_error}


def stub_the_judge(monkeypatch, *answers) -> list[str]:
    """The judge model answers with the given answers in turn; returns the prompts it gets."""
    prompts, left = [], list(answers)

    def judge(messages):
        [message] = messages
        prompts.append(message.content)
        return left.pop(0)

    monkeypatch.setattr(judges, "build_judge_model", lambda schema: RunnableLambda(judge))
    return prompts


@pytest.mark.parametrize(
    "draft, statements",
    [
        ("A site [osm-way-1].", [("A site [osm-way-1].", ("osm-way-1",))]),
        (
            "A workshop [osm-way-1] makes parts.",
            [("A workshop [osm-way-1]", ("osm-way-1",)), ("makes parts.", ())],
        ),
        (
            "A workshop [osm-way-1]. A depot [osm-way-2].",
            [("A workshop [osm-way-1].", ("osm-way-1",)), ("A depot [osm-way-2].", ("osm-way-2",))],
        ),
        (
            "Two sites [osm-way-1][osm-way-2].",
            [("Two sites [osm-way-1][osm-way-2].", ("osm-way-1", "osm-way-2"))],
        ),
        (
            "Two sites [osm-way-1] [osm-way-2].",
            [("Two sites [osm-way-1] [osm-way-2].", ("osm-way-1", "osm-way-2"))],
        ),
        ("A site [osm-way-1][osm-way-1].", [("A site [osm-way-1][osm-way-1].", ("osm-way-1",))]),
        (
            "A site [osm-way-1]. It can bring lorries.",
            [("A site [osm-way-1].", ("osm-way-1",)), ("It can bring lorries.", ())],
        ),
        (
            "A site\n\n[osm-way-1] and more.",
            [("A site", ()), ("and more.", ())],
        ),
        (
            "Two sites [osm-way-1], [osm-way-2].",
            [("Two sites [osm-way-1], [osm-way-2].", ("osm-way-1", "osm-way-2"))],
        ),
        (
            "Two sites. [osm-way-1]. [osm-way-2].",
            [("Two sites. [osm-way-1]. [osm-way-2].", ("osm-way-1", "osm-way-2"))],
        ),
        (
            "Workshops [osm-way-1] and [osm-way-2].",
            [("Workshops [osm-way-1] and [osm-way-2].", ("osm-way-1", "osm-way-2"))],
        ),
        (
            "A workshop 118 m away. It makes parts. It can be loud [osm-way-1].",
            [
                (
                    "A workshop 118 m away. It makes parts. It can be loud [osm-way-1].",
                    ("osm-way-1",),
                )
            ],
        ),
        (
            '**A workshop [osm-way-1]**. It is called "a yard [osm-way-2]". ',
            [
                ("**A workshop [osm-way-1]**.", ("osm-way-1",)),
                ('It is called "a yard [osm-way-2]".', ("osm-way-2",)),
            ],
        ),
        (
            "`A site [osm-way-1]`. ~~A depot [osm-way-2]~~. „A yard [osm-way-3]“.",
            [
                ("`A site [osm-way-1]`.", ("osm-way-1",)),
                ("~~A depot [osm-way-2]~~.", ("osm-way-2",)),
                ("„A yard [osm-way-3]“.", ("osm-way-3",)),
            ],
        ),
        ("___\n\n1.\n\nA site [osm-way-1].", [("A site [osm-way-1].", ("osm-way-1",))]),
        (
            "Not investigated:\n- A site, 230 m [osm-way-1]\n- A depot, 400 m [osm-way-2]\n- **",
            [
                ("Not investigated:\n- A site, 230 m [osm-way-1]", ("osm-way-1",)),
                ("- A depot, 400 m [osm-way-2]", ("osm-way-2",)),
            ],
        ),
    ],
    ids=[
        "a citation at the end",
        "a citation in the middle",
        "two objects",
        "a group",
        "a group with a space",
        "an id twice",
        "text after the citation",
        "a citation never reaches back over a paragraph",
        "a comma between citations",
        "a full stop between citations",
        "and between citations",
        "sentences before one citation",
        "markup and quotes after a citation",
        "code, struck text and german quotes after a citation",
        "no letter",
        "a list",
    ],
)
def test_the_draft_is_split_after_each_group_of_citations(draft, statements):
    assert split_into_statements(draft) == [Statement(text, cited) for text, cited in statements]


def test_the_support_judge_gets_the_cited_objects_sources_but_not_the_findings_result(
    monkeypatch,
):
    finding = Finding.model_validate(
        STATE.findings[0].model_dump() | {"status": "operating", "key_facts": ["only a key fact"]}
    )
    the_map = MAP.model_copy(update={"content": "Andere Straße 9, an object nobody cites"})
    state = STATE.model_copy(
        update={"findings": [finding], "sources": [the_map, PAGE], "failures": ["web search"]}
    )
    prompts = stub_the_judge(monkeypatch, answer(SUPPORTED))
    grade = judge_support(Statement("A workshop [osm-way-1].", ("osm-way-1",)), state, DATE)
    assert grade == SUPPORTED
    [prompt] = prompts
    assert "<statement>\nA workshop [osm-way-1].\n</statement>" in prompt
    assert "The report was written on 2026-10-10." in prompt
    assert "118 m" in prompt and "landuse=industrial\nTeststraße 1, 13597 Berlin" in prompt
    assert "Investigation: identified\n" in prompt
    assert f'<page url="{PAGE.url}">\n{PAGE.content}\n</page>' in prompt
    assert "failed after their retries, so their part of the report is missing: web search." in (
        prompt
    )
    assert "Andere Straße" not in prompt  # the map response, which has other objects too
    assert "operating" not in prompt and "identified as" not in prompt
    assert "only a key fact" not in prompt


def test_the_support_judge_gets_only_the_pages_that_each_cited_finding_cites(monkeypatch):
    depot = SITE.model_copy(
        update={
            "id": "osm-way-2",
            "addresses": ["Teststraße 9, 13597 Berlin"],
            "distance_from_property_m": 230,
        }
    )
    from_the_map = Finding(
        map_object_id="osm-way-2",
        outcome="identified",
        identified_type="logistics",
        status=None,
        key_facts=["Teststraße 9"],
        evidence_ids=["overpass-1"],
    )
    the_map = MAP.model_copy(update={"content": "Andere Straße 9, an object nobody cites"})
    state = STATE.model_copy(
        update={
            "map_objects": [SITE, depot],
            "findings": [Finding.unidentified("osm-way-1"), from_the_map],
            "sources": [the_map, PAGE],
        }
    )
    prompts = stub_the_judge(monkeypatch, answer(SUPPORTED))
    judge_support(
        Statement("Two sites [osm-way-1][osm-way-2].", ("osm-way-1", "osm-way-2")), state, DATE
    )
    [prompt] = prompts
    assert '<object id="osm-way-1">' in prompt and '<object id="osm-way-2">' in prompt
    assert "Investigation: could not be identified\n" in prompt
    assert "230 m" in prompt and "Teststraße 9, 13597 Berlin" in prompt
    assert "<page" not in prompt  # PAGE is stored, but no finding cites it
    assert "Andere Straße" not in prompt  # the map response, though the finding cites it
    assert "No unnamed industrial area was found" not in prompt


def test_the_support_judge_is_told_that_an_object_was_not_investigated(monkeypatch):
    prompts = stub_the_judge(monkeypatch, answer(SUPPORTED))
    state = STATE.model_copy(update={"findings": []})
    judge_support(Statement("A site [osm-way-1].", ("osm-way-1",)), state, DATE)
    assert "Investigation: not investigated\n" in prompts[0] and "<page" not in prompts[0]


def test_a_statement_without_a_citation_gets_only_the_facts_about_the_run(monkeypatch):
    prompts = stub_the_judge(monkeypatch, answer(SUPPORTED))
    state = RunState(property=Address(text="Freiheit 22, 13597 Berlin"))
    judge_support(Statement("Nothing was found.", ()), state, DATE)
    assert "<object" not in prompts[0]
    assert "No source failed." in prompts[0]
    assert "No unnamed industrial area was found near the property." in prompts[0]


def test_the_interpretation_judge_gets_every_object_and_the_failures_but_no_pages(monkeypatch):
    prompts = stub_the_judge(monkeypatch, answer(INTERPRETED))
    state = STATE.model_copy(update={"failures": ["web search"]})
    grade = judge_interpretation("A workshop [osm-way-1].", state)
    assert grade.verdict == "pass"
    [prompt] = prompts
    assert "- osm-way-1, 118 m from the property: identified as production, status not known" in (
        prompt
    )
    assert "<failures>\nweb search\n</failures>" in prompt
    assert "<report>\nA workshop [osm-way-1].\n</report>" in prompt
    assert PAGE.content not in prompt


def test_the_interpretation_judge_is_told_what_was_not_identified_or_investigated(monkeypatch):
    other = SITE.model_copy(update={"id": "osm-way-2", "distance_from_property_m": 230})
    state = STATE.model_copy(
        update={"map_objects": [SITE, other], "findings": [Finding.unidentified("osm-way-1")]}
    )
    prompts = stub_the_judge(monkeypatch, answer(INTERPRETED))
    judge_interpretation("A site [osm-way-1].", state)
    assert "- osm-way-1, 118 m from the property: could not be identified\n" in prompts[0]
    assert "- osm-way-2, 230 m from the property: not investigated\n" in prompts[0]


def test_the_no_verdict_judge_gets_only_the_draft(monkeypatch):
    prompts = stub_the_judge(
        monkeypatch, answer(NoVerdictGrade(reason="A verdict.", free_of_verdicts="no"))
    )
    grade = judge_no_verdict("A good place to live [osm-way-1].")
    assert grade.verdict == "fail"
    assert "<report>\nA good place to live [osm-way-1].\n</report>" in prompts[0]


@pytest.mark.parametrize(
    "bad",
    [
        answer(SUPPORTED, stop_reason="max_tokens"),
        answer(None, parsing_error="bad JSON"),
        answer(None),
    ],
    ids=["cut off", "does not parse", "nothing parsed"],
)
def test_a_bad_answer_is_an_error_not_a_grade(monkeypatch, bad):
    prompts = stub_the_judge(monkeypatch, bad)
    with pytest.raises(JudgeError):
        judge_no_verdict("A site [osm-way-1].")
    assert len(prompts) == 1  # not asked again


@pytest.mark.parametrize(
    "answers, verdict",
    [
        (["yes", "yes"], "pass"),
        (["yes", "unknown"], "unknown"),
        (["unknown", "no"], "fail"),
    ],
)
def test_a_no_fails_and_an_unknown_leaves_the_verdict_unknown(answers, verdict):
    assert combine(answers) == verdict


def test_the_interpretation_verdict_comes_from_all_four_answers():
    no = QuestionAnswer(reason="It says nothing was found.", answer="no")
    assert INTERPRETED.model_copy(update={"tells_failures": no}).verdict == "fail"

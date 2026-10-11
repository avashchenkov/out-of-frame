"""The LLM judges of the report, see docs/eval-architecture.md#llm-judges: support,
interpretation and no verdict. Each grades the report's draft, the model's own text before
code fills in its references, in a model call of its own, by its rubric in a template here.

Their grades are not quoted until the judges pass calibration in roadmap step 10.
"""

import datetime as dt
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

import jinja2
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from pydantic import Field

from out_of_frame import research_scope
from out_of_frame.config import JUDGE_MODEL
from out_of_frame.record import Record
from out_of_frame.report import CITATION
from out_of_frame.state import RunState

type Answer = Literal["yes", "no", "unknown"]
type Verdict = Literal["pass", "fail", "unknown"]

# A group of citations, with only spaces between them, and the punctuation, quotes and markup
# after it, which belong to the sentence the group ends: "**A site [osm-way-1][osm-way-2]**."
CITATIONS = re.compile(rf"(?:{CITATION.pattern}\s*)+" + r"""[.,;:!?)"'“”’»*_~`]*""")


class SupportGrade(Record):
    """The support judge's answer on one statement."""

    reason: str = Field(
        description="The claim that decides the grade and the source that backs or "
        "contradicts it, in one or two sentences."
    )
    grade: Literal["supported", "unsupported", "contradicted", "unknown"] = Field(
        description="The statement's grade, by the rules."
    )


class QuestionAnswer(Record):
    reason: str = Field(
        description="Why, in one or two sentences; for a no, quote the words of the report "
        "that are wrong, or name what is missing."
    )
    answer: Answer


class InterpretationGrade(Record):
    """The interpretation judge's answers on one report, one per question of its rubric."""

    explains_meaning: QuestionAnswer = Field(description="Question 1.")
    lists_unclear_objects: QuestionAnswer = Field(description="Question 2.")
    tells_failures: QuestionAnswer = Field(description="Question 3.")
    fits_type: QuestionAnswer = Field(description="Question 4.")

    @property
    def verdict(self) -> Verdict:
        return combine(
            [
                self.explains_meaning.answer,
                self.lists_unclear_objects.answer,
                self.tells_failures.answer,
                self.fits_type.answer,
            ]
        )


class NoVerdictGrade(Record):
    """The no verdict judge's answer on one report."""

    reason: str = Field(description="Why, in one or two sentences; for a no, quote the report.")
    free_of_verdicts: Answer = Field(
        description="yes if the report has no advice, score or verdict; no if it has one; "
        "unknown only if you cannot tell."
    )

    @property
    def verdict(self) -> Verdict:
        return combine([self.free_of_verdicts])


class JudgeError(Exception):
    """A judge's answer was cut off or does not parse. It is not asked again: the saved run can
    be judged again instead."""


@dataclass(frozen=True)
class Statement:
    """A part of the draft that the support judge grades on its own, with the objects it cites:
    the text up to a group of citations, as the report prompt asks the model to cite an object
    right after the sentences about it. Text after a paragraph's last citation cites nothing."""

    text: str
    cited: tuple[str, ...]


def split_into_statements(draft: str) -> list[Statement]:
    """The draft's statements, in order. A piece that states nothing of its own but cites, such
    as ", [osm-way-2]." in "Two sites [osm-way-1], [osm-way-2].", belongs to the statement
    before it. A piece that states nothing, such as a list marker, is left out."""
    statements = []
    for paragraph in re.split(r"\n\s*\n", draft):
        ends = [group.end() for group in CITATIONS.finditer(paragraph)]
        texts: list[str] = []
        for start, end in zip([0, *ends], [*ends, len(paragraph)], strict=True):
            piece = paragraph[start:end]
            if states_something(piece) or not texts:
                texts.append(piece)
            elif CITATION.search(piece):
                texts[-1] += piece
        statements += [
            Statement(text.strip(), tuple(dict.fromkeys(CITATION.findall(text))))
            for text in texts
            if states_something(text)
        ]
    return statements


def states_something(text: str) -> bool:
    """Whether the text has a letter of its own, beyond its citations and the word "and"."""
    rest = re.sub(r"\band\b", "", CITATION.sub("", text), flags=re.IGNORECASE)
    return re.search(r"[^\W\d_]", rest) is not None


def judge_support(statement: Statement, state: RunState, date: dt.date) -> SupportGrade:
    """Whether the sources of the objects the statement cites back it, on the date of the run.
    The judge gets each object's map data, distance and how its investigation ended, and the
    web pages its finding cites, but not the finding's type and status: the agent's own
    conclusion backs nothing."""
    objects = {map_object.id: map_object for map_object in state.map_objects}
    findings = {finding.map_object_id: finding for finding in state.findings}
    sources = {source.id: source for source in state.sources}
    cited = [objects[id] for id in statement.cited]
    pages = {
        map_object.id: [
            sources[id]
            for id in (findings[map_object.id].evidence_ids if map_object.id in findings else [])
            # The object's map data is its map_text(): the stored map response has every object
            # the map returned, so it could back a claim about another one.
            if sources[id].kind == "web search"
        ]
        for map_object in cited
    }
    prompt = render(
        "support.md.j2",
        date=date.isoformat(),
        statement=statement.text,
        objects=cited,
        findings=findings,
        pages=pages,
        failures=state.failures,
        nothing_found=is_nothing_found(state),
        types=research_scope.load().identified_types,
    )
    return ask(SupportGrade, prompt)


def judge_interpretation(draft: str, state: RunState) -> InterpretationGrade:
    """Whether the draft explains what its facts mean for a buyer, as the rubric asks. The judge
    gets every object with its distance and the type and status of its finding, and the failed
    sources, so that it can see what the draft leaves out; it gets no pages."""
    scope = research_scope.load()
    prompt = render(
        "interpretation.md.j2",
        draft=draft,
        map_objects=state.map_objects,
        findings={finding.map_object_id: finding for finding in state.findings},
        failures=state.failures,
        nothing_found=is_nothing_found(state),
        types=scope.identified_types,
        statuses=scope.finding_statuses,
    )
    return ask(InterpretationGrade, prompt)


def judge_no_verdict(draft: str) -> NoVerdictGrade:
    """Whether the draft is free of advice, scores and verdicts on buying or renting."""
    return ask(NoVerdictGrade, render("no_verdict.md.j2", draft=draft))


def combine(answers: list[Answer]) -> Verdict:
    """A judge's verdict from its answers: fail on any no, otherwise unknown on any unknown."""
    if "no" in answers:
        return "fail"
    return "unknown" if "unknown" in answers else "pass"


def is_nothing_found(state: RunState) -> bool:
    """TODO: in step 6, the state has every object found, not only the one investigated."""
    return not state.map_objects and "map" not in state.failures


def ask[T: Record](schema: type[T], prompt: str) -> T:
    return read_answer(build_judge_model(schema).invoke([HumanMessage(prompt)]))


@cache
def build_judge_model(schema: type[Record]):
    """The judge model with native structured output, so that it can think before it answers,
    as in out_of_frame.prompt_injection."""
    return ChatAnthropic(model=JUDGE_MODEL).with_structured_output(
        schema, method="json_schema", include_raw=True
    )


def read_answer(answer):
    """The parsed answer of build_judge_model(); one that was cut off or does not parse raises:
    the parser would complete a cut-off answer into a valid one."""
    stop_reason = answer["raw"].response_metadata.get("stop_reason")
    if stop_reason != "end_turn" or answer["parsing_error"] or answer["parsed"] is None:
        raise JudgeError(f"stop reason {stop_reason}, parsing error {answer['parsing_error']}")
    return answer["parsed"]


def render(template: str, **values) -> str:
    """A rubric template from this folder, filled in with the values."""
    return load_rubrics().get_template(template).render(**values)


@cache
def load_rubrics() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(Path(__file__).parent),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )

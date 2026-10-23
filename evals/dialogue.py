"""Run written replies through the normal agent for evals and offline tests."""

import datetime as dt

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from out_of_frame.agent import RESEARCH_STARTS, build_graph, find_question, start, start_thread
from out_of_frame.investigation import Context
from out_of_frame.state import RunState
from out_of_frame.web_search import WebSearch


class UnansweredQuestionError(Exception):
    """The agent asked a question after the user's replies had run out."""


def run(
    messages: list[str],
    date: dt.date,
    web_search: WebSearch,
    input_only: bool = False,
    config: RunnableConfig | None = None,
) -> RunState:
    """A run without a person: the first message starts it, and each next one answers the
    agent's next question, as in the evals. With input_only, the run stops once the input is
    complete, before research starts, as in the input loop suite. A caller that gives the
    run's thread can read the state where the run stopped, even after an error."""
    graph, config = build_graph(), config or start_thread()
    command: RunState | Command = start(messages[0])
    stop = RESEARCH_STARTS if input_only else None
    for reply in [*messages[1:], None]:
        graph.invoke(command, config, context=Context(date, web_search), interrupt_before=stop)
        question = find_question(graph, config)
        if question is None:
            break
        if reply is None:
            raise UnansweredQuestionError(question)
        command = Command(resume=reply)
    return RunState.model_validate(graph.get_state(config).values)

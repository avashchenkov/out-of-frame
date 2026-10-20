"""The prices of the models and of Tavily, read from data/prices.yaml, for the cost of a run."""

import datetime as dt
import logging
from functools import cache
from importlib.resources import files

import yaml
from pydantic import NonNegativeFloat

from out_of_frame.record import Record

log = logging.getLogger(__name__)


class ModelPrice(Record):
    input_per_mtok: NonNegativeFloat  # USD for a million input tokens
    output_per_mtok: NonNegativeFloat  # USD for a million output tokens


class TavilyPrice(Record):
    credit: NonNegativeFloat  # USD for one credit
    search_credits: NonNegativeFloat  # credits for one search
    page_credits: NonNegativeFloat  # credits for one page read


class Prices(Record):
    as_of: dt.date  # when the prices were checked; a run records it, so stale prices show
    models: dict[str, ModelPrice]  # by model name, such as claude-haiku-5-5
    tavily: TavilyPrice

    def compute_cost(
        self, model: str, input_tokens: int, output_tokens: int, credits: float
    ) -> float:
        """USD for the model's tokens and the Tavily credits."""
        price = self.models[model]
        tokens = input_tokens * price.input_per_mtok + output_tokens * price.output_per_mtok
        return tokens / 1_000_000 + credits * self.tavily.credit


@cache
def load() -> Prices:
    """The prices, read once."""
    path = files("out_of_frame").joinpath("data/prices.yaml")
    return Prices.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def compute_run_cost(usage: dict, credits: float) -> float:
    """USD for the models' tokens, as get_usage_metadata_callback counts them, and the Tavily
    credits. The usage is keyed by the API's model snapshot, which begins with the model's name,
    so each snapshot is priced as the longest model name that begins it: one run can call the
    agent's model, the injection check's and the judges'. A snapshot with no price is left out
    with a warning: the run has been paid for, so its record must still be saved."""
    prices = load()
    cost = credits * prices.tavily.credit
    for snapshot, used in usage.items():
        names = [name for name in prices.models if snapshot.startswith(name)]
        if not names:
            log.warning(
                "no price for %s, left out of the cost: add it to data/prices.yaml", snapshot
            )
            continue
        model = max(names, key=len)
        cost += prices.compute_cost(model, used["input_tokens"], used["output_tokens"], 0)
    return cost

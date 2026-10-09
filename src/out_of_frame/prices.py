"""The prices of the model and of Tavily, read from data/prices.yaml, for the cost of a run."""

import datetime as dt
from functools import cache
from importlib.resources import files

import yaml
from pydantic import NonNegativeFloat

from out_of_frame.record import Record


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

    def cost(self, model: str, input_tokens: int, output_tokens: int, credits: float) -> float:
        """USD for the model's tokens and the Tavily credits."""
        price = self.models[model]
        tokens = input_tokens * price.input_per_mtok + output_tokens * price.output_per_mtok
        return tokens / 1_000_000 + credits * self.tavily.credit


@cache
def load() -> Prices:
    """The prices, read once."""
    path = files("out_of_frame").joinpath("data/prices.yaml")
    return Prices.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

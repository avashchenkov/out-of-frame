"""The prices file and the cost of a run."""

import datetime as dt

import pytest

from out_of_frame import prices
from out_of_frame.config import MODEL
from out_of_frame.prices import ModelPrice, Prices, TavilyPrice


def test_the_prices_file_has_the_configured_model():
    assert MODEL in prices.load().models


def test_the_cost_adds_the_tokens_and_the_credits():
    table = Prices(
        as_of=dt.date(2026, 10, 9),
        models={"m": ModelPrice(input_per_mtok=1.0, output_per_mtok=5.0)},
        tavily=TavilyPrice(credit=0.01, search_credits=1.0, page_credits=0.2),
    )
    assert table.compute_cost("m", 2_000_000, 1_000_000, credits=3.0) == pytest.approx(2 + 5 + 0.03)

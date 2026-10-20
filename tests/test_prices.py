"""The prices file and the cost of a run."""

import datetime as dt

import pytest

from out_of_frame import prices
from out_of_frame.config import INJECTION_MODEL, JUDGE_MODEL, MODEL
from out_of_frame.prices import ModelPrice, Prices, TavilyPrice


def test_the_prices_file_has_the_configured_models():
    assert {MODEL, INJECTION_MODEL, JUDGE_MODEL} <= prices.load().models.keys()


def test_the_cost_adds_the_tokens_and_the_credits():
    table = Prices(
        as_of=dt.date(2026, 10, 9),
        models={"m": ModelPrice(input_per_mtok=1.0, output_per_mtok=5.0)},
        tavily=TavilyPrice(credit=0.01, search_credits=1.0, page_credits=0.2),
    )
    assert table.compute_cost("m", 2_000_000, 1_000_000, credits=3.0) == pytest.approx(2 + 5 + 0.03)


def test_each_snapshot_is_priced_as_the_longest_model_name_that_begins_it(monkeypatch, caplog):
    table = Prices(
        as_of=dt.date(2026, 10, 9),
        models={
            "m": ModelPrice(input_per_mtok=1.0, output_per_mtok=1.0),
            "m-big": ModelPrice(input_per_mtok=10.0, output_per_mtok=10.0),
        },
        tavily=TavilyPrice(credit=0.01, search_credits=1.0, page_credits=0.2),
    )
    monkeypatch.setattr(prices, "load", lambda: table)
    usage = {
        "m-20261001": {"input_tokens": 1_000_000, "output_tokens": 0},
        "m-big-20261001": {"input_tokens": 1_000_000, "output_tokens": 0},
    }
    assert prices.compute_run_cost(usage, credits=2.0) == pytest.approx(1 + 10 + 0.02)
    usage["other"] = {"input_tokens": 1_000_000, "output_tokens": 0}  # left out, not a crash
    assert prices.compute_run_cost(usage, credits=2.0) == pytest.approx(1 + 10 + 0.02)
    assert "no price for other" in caplog.text

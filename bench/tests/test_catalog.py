"""OpenRouter's model list, read for what a run needs: prices and whether a model takes tools."""
from __future__ import annotations

import catalog

LISTING = {"data": [
    {"id": "vendor/paid", "pricing": {"prompt": "0.000002", "completion": "0.00001"},
     "supported_parameters": ["max_tokens", "tools", "tool_choice"]},
    {"id": "vendor/small:free", "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["max_tokens"]},
]}


def test_prices_are_dollars_per_token_and_tools_come_from_the_supported_parameters() -> None:
    found = catalog.parse(LISTING)
    assert found["vendor/paid"] == catalog.Listing(input_price=2e-06, output_price=1e-05, tools=True)
    assert found["vendor/small:free"].tools is False


def test_a_model_that_costs_nothing_is_free() -> None:
    found = catalog.parse(LISTING)
    assert found["vendor/small:free"].free and not found["vendor/paid"].free

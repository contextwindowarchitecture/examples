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


def test_a_listing_keeps_what_explains_a_models_numbers() -> None:
    listed = {"data": [{**LISTING["data"][0], "context_length": 500000, "architecture": {"tokenizer": "Grok"},
                        "default_parameters": {"temperature": 0.7, "top_p": 0.95}}]}
    found = catalog.parse(listed)["vendor/paid"]
    # Its own tokenizer, by family; its context limit; and the temperature it samples at when a request sets none.
    assert (found.tokenizer, found.context, found.temperature) == ("Grok", 500000, 0.7)
    bare = catalog.parse(LISTING)["vendor/paid"]  # a listing that says none of it
    assert (bare.tokenizer, bare.context, bare.temperature) == (None, None, None)


def test_a_model_that_costs_nothing_is_free() -> None:
    found = catalog.parse(LISTING)
    assert found["vendor/small:free"].free and not found["vendor/paid"].free

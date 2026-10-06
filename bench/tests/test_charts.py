"""The charts on each page of numbers: what to draw, from values the page already holds."""
from __future__ import annotations

from typing import Any

import charts
import metrics
from test_metrics import MODEL, assembly, call, listed, result


def drawn(pages: list[dict[str, Any]], results: list[metrics.Result], models: list[str], page: str, chart: str) -> dict[str, Any]:
    found = {one["id"]: one for one in charts.add(pages, results, models)}
    return next(one for one in found[page]["charts"] if one["id"] == chart)


def test_a_request_is_a_row_of_its_budget_by_plane() -> None:
    made = [assembly(estimate=300, budget=1500, sent=(("governance.instructions", 140), ("evidence.knowledge", 110), ("interaction.query", 10)))]
    chart = drawn([metrics.decisions(made, [MODEL])], [], [MODEL], "decisions", "budget")
    [row] = chart["rows"]
    assert (chart["kind"], chart["x"]["unit"], row["label"]) == ("rows", "percent", "01-docs-qa/01-answer")
    # Each plane's tokens as a share of the route's budget, one after the other, then what the renderer adds around them.
    assert [(mark["tone"], round(mark["from"], 4), round(mark["to"], 4), mark["value"]) for mark in row["marks"]] == [
        ("governance", 0, 0.0933, 140), ("state", 0.0933, 0.0933, 0), ("evidence", 0.0933, 0.1667, 110),
        ("interaction", 0.1667, 0.1733, 10), ("around", 0.1733, 0.2, 40)]
    assert [entry["tone"] for entry in chart["legend"]] == ["governance", "state", "evidence", "interaction", "around"]


def test_each_model_has_a_panel_of_its_count_against_the_estimate() -> None:
    sizes = (("01-docs-qa/01-answer", 100), ("02-account-aware/01-team-plan", 200), ("03-budget-and-routes/01-large-route", 300))
    log = "03-budget-and-routes/03-pasted-log"
    calls = [call(model="a/adds", task=task, example=task.split("/")[0], estimate=size, prompt=size + 1000) for task, size in sizes]
    calls.append(call(model="a/adds", task=log, example="03-budget-and-routes", estimate=400, prompt=1800, budget=6000))
    chart = drawn([metrics.tokens(calls, ["a/adds"], frozenset({log}))], [], ["a/adds"], "tokens", "counts")
    [panel] = chart["panels"]
    assert (chart["kind"], panel["label"], panel["line"]) == ("panels", "adds", {"intercept": 1000, "slope": 1})
    assert panel["note"] == "adds 1,000, then counts 1.00×"
    assert panel["points"][0] == {"x": 100, "y": 1100, "ratio": 11, "label": "01-docs-qa/01-answer", "hollow": False}
    assert panel["points"][-1]["hollow"] is True  # the pasted log, which the line was not drawn through
    # What a count is set against: the estimate itself, and the estimate with the margin the routes declare.
    assert chart["rules"] == [{"label": "The assembler's estimate", "slope": 1, "tone": "quiet"},
                              {"label": "The estimate plus the declared margin, 15%", "slope": 1.15, "tone": "accent"}]


def test_a_request_is_a_cell_per_model_filled_where_the_declared_margin_did_not_cover_it() -> None:
    sizes = (("01-docs-qa/01-answer", 100), ("02-account-aware/01-team-plan", 200), ("03-budget-and-routes/01-large-route", 300))
    models = ["b/adds", "a/exact"]
    calls = [call(model=model, task=task, example=task.split("/")[0], estimate=size, prompt=int(size * rate) + added)
             for model, rate, added in (("b/adds", 1.0, 1000), ("a/exact", 1.05, 0)) for task, size in sizes]
    page = metrics.tokens(calls, models)
    chart = drawn([page], [], models, "tokens", "margins")
    # The models in the order of the margin they needed, the least first, so what the margin missed gathers to the right.
    assert (chart["kind"], chart["unit"], chart["columns"]) == ("grid", "percent", ["exact", "adds"])
    table = next(table for table in page["tables"] if table["id"] == "margin_by_case")["rows"]
    assert [row["label"] for row in chart["rows"]] == [row["case"] for row in table]
    assert chart["rows"][0]["cells"] == [{"value": table[0]["a/exact"], "over": False}, {"value": table[0]["b/adds"], "over": True}]
    # A column opens its model's card on the page.
    assert chart["opens"] == ["a/exact", "b/adds"]


def test_a_pass_rate_is_a_dot_inside_the_range_it_could_have() -> None:
    results = [result(repeat=n, checks=(("answer answered", True), ("answer mentions_any", n == 1))) for n in (1, 2)]
    chart = drawn([metrics.verdicts([], results, [MODEL])], results, [MODEL], "checks", "passed")
    [row] = chart["rows"]
    low, high = metrics.wilson(3, 4)
    assert row["label"] == "model" and chart["x"]["zero"] is False
    assert row["marks"] == [{"mark": "range", "from": round(low, 6), "to": round(high, 6), "tone": "quiet", "name": "Where the rate could lie"},
                            {"mark": "dot", "x": 0.75, "tone": "ink", "name": "Checks passed"}]


def test_a_case_is_a_cell_per_model_filled_by_the_repeats_it_passed() -> None:
    results = [result(model=model, repeat=n, checks=(("answer answered", model == "a/steady" or n == 1),)) for model in ("a/steady", "b/flips") for n in (1, 2, 3)]
    results += [result(model="a/steady", case="01-docs-qa/03-off-topic", checks=(), answer=None)]  # refused: nothing to grade
    pages = [metrics.stability(results, ["a/steady", "b/flips"])]
    chart = drawn(pages, results, ["a/steady", "b/flips"], "stability", "repeats")
    assert (chart["kind"], chart["columns"]) == ("grid", ["steady", "flips"])
    assert chart["rows"] == [{"label": "01-docs-qa/01-answer · after", "cells": [{"value": 3, "of": 3}, {"value": 1, "of": 3}]}]


def test_cost_sets_each_model_where_its_price_and_its_steadiness_put_it() -> None:
    results = [result(model=model, repeat=n, checks=(("answer answered", model == "a/steady" or n == 1),)) for model in ("a/steady", "b/flips", "c/free") for n in (1, 2)]
    models = {"a/steady": listed(cost=0.02), "b/flips": listed(cost=0.004), "c/free": listed(cost=0, free=True, input_price=0, output_price=0)}
    pages = [metrics.cost([], results, {"models": models, "jobs": []}), metrics.stability(results, list(models))]
    chart = drawn(pages, results, list(models), "cost", "frontier")
    assert (chart["kind"], chart["x"]["log"], chart["y"]["unit"]) == ("scatter", True, "percent")
    # A model that cost nothing has no place on a scale of ratios, and is left off.
    assert chart["points"] == [{"label": "steady", "x": 0.01, "y": 1, "opens": "a/steady"}, {"label": "flips", "x": 0.004, "y": 0, "opens": "b/flips"}]


def test_what_a_model_cost_is_a_bar_of_prompt_and_completion_against_what_was_planned() -> None:
    models = {"b/cheap": listed(cost=0.004), "a/dear": listed(cost=0.02, planned={"likely": 0.03})}
    calls = [call(model="a/dear", prompt_cost=0.001, completion_cost=0.003), call(model="b/cheap")]
    chart = drawn([metrics.cost(calls, [], {"models": models, "jobs": []})], [], list(models), "cost", "spent")
    assert (chart["kind"], chart["x"]) == ("rows", {"label": "Dollars spent", "unit": "usd", "zero": True})
    # The largest spend first. Each row opens its model's card.
    assert [(row["label"], row["opens"]) for row in chart["rows"]] == [("dear", "a/dear"), ("cheap", "b/cheap")]
    # What was spent, split by the share of the charge its hosts said was prompt, and the plan marked against it.
    assert chart["rows"][0]["marks"] == [
        {"mark": "segment", "from": 0, "to": 0.005, "tone": "ink", "name": "Prompt, 25% of $0.020", "value": 0.005, "unit": "usd"},
        {"mark": "segment", "from": 0.005, "to": 0.02, "tone": "quiet", "name": "Completion", "value": 0.015, "unit": "usd"},
        {"mark": "tick", "x": 0.03, "tone": "accent", "tall": True, "name": "Planned, likely"}]
    # A model whose hosts did not say how the charge splits is one bar, and one with no plan has nothing marked.
    assert chart["rows"][1]["marks"] == [{"mark": "bar", "x": 0.004, "tone": "ink", "name": "Spent"}]


def test_an_agents_count_is_a_line_through_its_inferences_under_the_budget() -> None:
    results = [result(case="04-tools/01-owner-reenables", variant=None, repeat=n, estimates=estimates, budget=4000)
               for n, estimates in enumerate(((1000, 1100, 1300), (1000, 1200), (1000,)), start=1)]
    chart = drawn([metrics.agents(results, [MODEL])], results, [MODEL], "agents", "growth")
    assert chart["kind"] == "lines" and chart["rules"] == [{"label": "The route's budget.input", "y": 4000, "tone": "accent"}]
    # The median count at each inference, across the tasks that reached it.
    assert chart["series"] == [{"label": "model", "points": [[1, 1000], [2, 1150], [3, 1300]]}]


def test_before_and_after_join_the_two_requests_one_model_answered() -> None:
    by_hand = {"variant": "before", "estimate": None, "budget": None, "margin": None, "assembly": None}
    calls = [call(**by_hand, prompt=500), call(prompt=400)]
    results = [result(variant="before"), result()]
    [chart] = [one for one in charts.add([metrics.before_after(calls, results, [MODEL])], results, [MODEL])[0]["charts"]]
    assert (chart["id"], chart["kind"], chart["title"]) == ("prompt-01-answer", "rows", "01-docs-qa/01-answer: prompt tokens, before and after")
    assert chart["rows"] == [{"label": "model", "marks": [
        {"mark": "link", "from": 500, "to": 400, "tone": "quiet"},
        {"mark": "ring", "x": 500, "tone": "ink", "name": "before.py, by hand"},
        {"mark": "dot", "x": 400, "tone": "ink", "name": "after.py, through CWA"}]}]


def test_a_models_wait_is_a_row_from_its_first_token_through_its_slowest_calls() -> None:
    models = ["b/slow", "a/quick"]
    calls = [call(model="b/slow", completion=200, reasoning=100, ms=ms, first_token=500, generating=ms - 200) for ms in (3000, 3000, 9000)]
    calls += [call(model="a/quick", ms=1000)]  # a run that holds no stats from OpenRouter for it
    chart = drawn([metrics.speed(calls, {"models": {model: listed() for model in models}, "jobs": []})], [], models, "speed", "wait")
    # Seconds span ten times and more between models, so the axis is a scale of ratios; the quickest median call is first.
    assert chart["x"] == {"label": "Seconds", "unit": "seconds", "log": True}
    assert [row["label"] for row in chart["rows"]] == ["quick", "slow"]
    # A row opens its model's card on the page.
    assert [row["opens"] for row in chart["rows"]] == ["a/quick", "b/slow"]
    # Marks in the order a reader meets them, each a median or a percentile of its own.
    assert chart["rows"][1]["marks"] == [
        {"mark": "link", "from": 0.5, "to": 9, "tone": "quiet"},
        {"mark": "dot", "x": 0.5, "tone": "ink", "name": "Median time to first token"},
        {"mark": "ring", "x": 1.65, "tone": "ink", "name": "First visible token, estimated"},
        {"mark": "tick", "x": 3, "tone": "ink", "tall": True, "name": "Median call"},
        {"mark": "tick", "x": 9, "tone": "quiet", "name": "Slow call"},
        {"mark": "tick", "x": 9, "tone": "quiet", "name": "Slowest calls"}]
    assert [mark["mark"] for mark in chart["rows"][0]["marks"]] == ["link", "tick", "tick", "tick"]


def test_what_a_model_cited_of_what_it_was_sent_is_a_bar() -> None:
    results = [result(sent=("help:a@1#0", "help:b@1#0"), cited=("help:a@1#0",), supported=0.9)]
    chart = drawn([metrics.grounding(results, [MODEL])], results, [MODEL], "grounding", "cited")
    assert chart["rows"] == [{"label": "model", "marks": [{"mark": "bar", "x": 0.5, "tone": "ink", "name": "Articles cited, of those sent"}]}]
    assert chart["x"] == {"label": "Articles cited, of those sent", "unit": "percent", "zero": True, "to": 1}


def test_every_chart_says_where_its_values_are_tabled() -> None:
    results = [result(case="04-tools/01-owner-reenables", variant=None, repeat=n, estimates=(1000, 1100), budget=4000) for n in (1, 2)]
    calls = [call(completion=200, reasoning=100, ms=3000, first_token=500, generating=2800)]
    summary = {"models": {MODEL: listed(cost=0.02)}, "jobs": []}
    pages = [metrics.decisions([assembly()], [MODEL]), metrics.tokens(calls, [MODEL]), metrics.cost(calls, results, summary), metrics.speed(calls, summary),
             metrics.stability(results, [MODEL]), metrics.grounding([result(sent=("help:a@1#0",), cited=("help:a@1#0",))], [MODEL]),
             metrics.agents(results, [MODEL]), metrics.verdicts(calls, results, [MODEL])]
    found = [chart for page in charts.add(pages, results, [MODEL]) for chart in page["charts"]]
    assert {chart["kind"] for chart in found} == {"rows", "panels", "grid", "scatter", "lines"}
    assert all(chart["values"] and chart["title"] and chart["how"] for chart in found)
    # The agents' chart is of a table on its own page: the count at each inference, by model.
    agents = next(page for page in pages if page["id"] == "agents")
    assert next(table for table in agents["tables"] if table["id"] == "growth")["rows"] == [{"model": MODEL, "1": 1000, "2": 1100}]


def test_a_page_with_nothing_to_draw_has_no_chart() -> None:
    pages = [metrics.tokens([], [MODEL]), metrics.verdicts([], [], [MODEL]), metrics.agents([], [MODEL]), metrics.decisions([], [MODEL])]
    assert all(page["charts"] == [] for page in charts.add(pages, [], [MODEL]))

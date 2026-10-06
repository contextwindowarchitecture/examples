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
    assert chart["points"] == [{"label": "steady", "x": 0.01, "y": 1}, {"label": "flips", "x": 0.004, "y": 0}]


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


def test_a_call_is_a_bar_with_the_wait_for_its_first_token_marked_on_it() -> None:
    calls = [call(completion=200, reasoning=100, ms=3000, first_token=500, generating=2800)]
    chart = drawn([metrics.speed(calls, {"models": {MODEL: listed()}, "jobs": []})], [], [MODEL], "speed", "wait")
    assert chart["rows"] == [{"label": "model", "marks": [
        {"mark": "bar", "x": 3, "tone": "quiet", "name": "Median call"},
        {"mark": "ring", "x": 1.65, "tone": "ink", "name": "First visible token, estimated"},
        {"mark": "dot", "x": 0.5, "tone": "ink", "name": "Median time to first token"}]}]
    unknown = drawn([metrics.speed([call(ms=3000)], {"models": {MODEL: listed()}, "jobs": []})], [], [MODEL], "speed", "wait")
    assert [mark["mark"] for mark in unknown["rows"][0]["marks"]] == ["bar"]  # a run that holds no stats from OpenRouter


def test_each_number_on_speed_is_a_strip_with_a_dot_per_model() -> None:
    models = ["a/quick", "b/slow"]
    calls = [call(model="a/quick", ms=1000), call(model="b/slow", ms=3000, attempts=2)]
    chart = drawn([metrics.speed(calls, {"models": {model: listed() for model in models}, "jobs": []})], [], models, "speed", "strips")
    found = {strip["label"]: strip for strip in chart["strips"]}
    assert chart["kind"] == "strips"
    assert found["Median call"] == {"label": "Median call", "unit": "seconds", "log": False,
                                    "points": [{"label": "quick", "x": 1}, {"label": "slow", "x": 3}]}
    # A count that is 0 for one model is set on an axis from zero, never on a scale of ratios.
    assert found["Calls tried more than once"]["log"] is False
    # A number every model holds the same value of has nothing to set apart.
    assert "Answers cut short" not in found
    wide = drawn([metrics.speed([call(model="a/quick", ms=1000), call(model="b/slow", ms=30000)], {"models": {model: listed() for model in models}, "jobs": []})],
                 [], models, "speed", "strips")
    # Values that span ten times or more are set on a scale of ratios, so the slowest does not crush the rest.
    assert next(strip for strip in wide["strips"] if strip["label"] == "Median call")["log"] is True


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

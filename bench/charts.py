"""The charts on each page of numbers: what to draw, from values the page already holds. The viewer draws them with D3
(viewer/charts.js) and computes nothing: a chart is a list of marks with their places on its axes.

    rows     a row per model or request on one axis, or on a scale of ratios: bars, dots, rings, ticks, ranges, links
             and stacked segments
    panels   one small plot per model on shared axes: its points, the line through them, and what they are set against
    grid     a cell per case and model
    scatter  a labelled point per model on two axes
    lines    a line per model

Colour does one job in each chart, named by a mark's tone: ink for the data, quiet for what it is set against, accent
for what the chart is about, and a plane's own colour for that plane. A model is never a colour: a dozen models are
more colours than stay apart, for any reader, so a model is a row, a panel or a label. A chart shows nothing a table
does not hold, and says where: its values.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any

from config import SAME_CONTEXT

PLANES = {"governance": "Governance", "state": "State", "evidence": "Evidence", "interaction": "Interaction",
          "around": "Around the items"}


def add(pages: list[dict[str, Any]], results: list[Any], models: list[str]) -> list[dict[str, Any]]:
    """Each page with its charts. results: the run's results (metrics.Result), for the charts no table holds."""
    by = {page["id"]: page for page in pages}
    for page in pages:
        page["charts"] = [chart for chart in CHARTS.get(page["id"], lambda *_: [])(by, results, models) if chart]
    return pages


def _decisions(by: dict[str, Any], results: list[Any], models: list[str]) -> list[dict[str, Any] | None]:
    budgets = {row["request"]: row["budget"] for row in _rows(by["decisions"], "requests")}

    def marks(row: dict[str, Any]) -> list[dict[str, Any]]:
        found, at = [], 0.0
        for tone, name in PLANES.items():
            share = row[tone] / budgets[row["request"]]
            found.append({"mark": "segment", "from": at, "to": at + share, "tone": tone, "name": name, "value": row[tone], "unit": "tokens"})
            at += share
        return found

    spent = _rows(by["decisions"], "planes")
    return [spent and {
        "id": "budget", "kind": "rows", "title": "How much of its budget each request used, and on what",
        "how": "Each of 01–03's requests as a bar of its route's budget.input: the tokens of the items it sent, by "
               "plane, then what the renderer adds around them. The space to the right is budget the request left.",
        "values": "Its values are in the tables of requests and of planes on this page.",
        "x": {"label": "Share of the route's budget.input", "unit": "percent", "zero": True, "to": 1},
        "legend": [{"mark": "segment", "tone": tone, "label": name} for tone, name in PLANES.items()],
        "rows": [{"label": row["request"], "marks": marks(row)} for row in spent]}]


def _tokens(by: dict[str, Any], results: list[Any], models: list[str]) -> list[dict[str, Any] | None]:
    page = by["tokens"]
    requests, slopes, added = _rows(page, "by_case"), _values(page, "tokens_per_estimated"), _values(page, "tokens_added")
    declared = sorted({row["declared"] for row in _rows(page, "margin_by_case")})

    def panel(model: str) -> dict[str, Any] | None:
        points = [{"x": row["estimate"], "y": row[model], "ratio": round(row[model] / row["estimate"], 6), "label": row["case"],
                   "hollow": row["question"] != "one line"} for row in requests if row.get(model) is not None]
        fitted = slopes.get(model) is not None
        return points and {"label": _short(model), "points": points,
                           "line": {"intercept": added[model], "slope": slopes[model]} if fitted else None,
                           "note": (f"adds {added[model]:,.0f}, then counts {slopes[model]:.2f}×" if added[model] >= 100
                                    else f"counts {slopes[model]:.2f}×") if fitted else "too few requests for a line"}

    panels = [found for model in models if (found := panel(model))]
    return [panels and {
        "id": "counts", "kind": "panels", "title": "The same requests, as each model's host counted them",
        "how": "One panel per model, all on the same axes. Each point is one of 01–03's requests: the assembler's "
               "estimate across, the host's count up. A hollow point is a request whose question pastes a block of "
               "text, which the line is not drawn through. A point above the accent line needed more than the margin "
               "its route declares.",
        "values": "Its values are in the table of requests on this page, and each line is two of the numbers above it.",
        "x": {"label": "The assembler's estimate", "unit": "tokens", "zero": True},
        "y": {"label": "The host's count", "unit": "tokens", "zero": True},
        "rules": [{"label": "The assembler's estimate", "slope": 1, "tone": "quiet"},
                  *([{"label": f"The estimate plus the declared margin, {declared[0]:.0%}", "slope": round(1 + declared[0], 6), "tone": "accent"}]
                    if len(declared) == 1 else [])],
        "legend": [{"mark": "dot", "tone": "ink", "label": "A request"}, {"mark": "ring", "tone": "ink", "label": "A request that pastes a block of text"},
                   {"mark": "line", "tone": "ink", "label": "The line through a model's requests"}],
        "panels": panels}, _margins(page, models)]


def _margins(page: dict[str, Any], models: list[str]) -> dict[str, Any] | None:
    """The margin each request needed, as a cell per request and model: the shape of Stability's grid, and the same
    reading, since what matters is the few cells the declared margin did not cover."""
    needed, margins = _values(page, "margin_needed"), _rows(page, "margin_by_case")
    order = sorted((model for model in models if needed.get(model) is not None), key=lambda model: needed[model])
    declared = sorted({row["declared"] for row in margins})
    return order and margins and {
        "id": "margins", "kind": "grid", "unit": "percent", "name": "Margin needed",
        "title": "Each request, and the models whose host needed more than its declared margin",
        "how": "A cell per 01–03 request and model, the models in the order of the margin they needed, the least "
               "first. A quiet cell is a request its route's declared margin covered: the host counted no more than "
               "the estimate plus " + (f"{declared[0]:.0%}" if len(declared) == 1 else "the route's margin") + ". A filled "
               "one did not, and says the margin it needed: the route's budget.input could be exceeded by that much.",
        "values": "Its values are in the table of the margin each request needed, on this page.",
        "columns": [_short(model) for model in order],
        "legend": [{"mark": "dot", "tone": "quiet", "label": "Covered by the declared margin"},
                   {"mark": "cell", "tone": "accent", "label": "Not covered, with the margin it needed"}],
        "rows": [{"label": row["case"], "cells": [None if row.get(model) is None else {"value": row[model], "over": row[model] > row["declared"]}
                                                  for model in order]} for row in margins]}


def _cost(by: dict[str, Any], results: list[Any], models: list[str]) -> list[dict[str, Any] | None]:
    price = _values(by["cost"], "cost_per_clean_result")
    steady = _values(by["stability"], "pass_every") if "stability" in by else {}
    points = [{"label": _short(model), "x": price[model], "y": steady[model]} for model in models
              if price.get(model) and steady.get(model) is not None]
    return [points and {
        "id": "frontier", "kind": "scatter", "title": "What a steady answer costs",
        "how": "Each model once: across, what the run spent for each of its results with every check passed, on a "
               "scale of ratios; up, the share of its cases it passed in every repeat. Up and to the left is steadier "
               "for less. A model that cost nothing has no place on a scale of ratios, and is left off.",
        "values": "Its values are a column of the table on this page and, for the cases passed, a column of the Stability page's.",
        "x": {"label": "Cost per result with every check passed", "unit": "usd", "log": True},
        "y": {"label": "Cases passed in every repeat", "unit": "percent", "zero": False},
        "points": points}]


def _speed(by: dict[str, Any], results: list[Any], models: list[str]) -> list[dict[str, Any] | None]:
    page = by["speed"]
    first, visible = _values(page, "first_token_p50"), _values(page, "first_visible")
    median, slow, slowest = _values(page, "seconds_p50"), _values(page, "seconds_p90"), _values(page, "seconds_p99")

    def marks(model: str) -> list[dict[str, Any]]:
        # In the order a reader meets them. A run that holds no stats from OpenRouter has no first token to mark.
        found = [*([{"mark": "dot", "x": first[model], "tone": "ink", "name": "Median time to first token"}] if first.get(model) else []),
                 *([{"mark": "ring", "x": visible[model], "tone": "ink", "name": "First visible token, estimated"}] if visible.get(model) else []),
                 {"mark": "tick", "x": median[model], "tone": "ink", "tall": True, "name": "Median call"},
                 {"mark": "tick", "x": slow[model], "tone": "quiet", "name": "Slow call"},
                 {"mark": "tick", "x": slowest[model], "tone": "quiet", "name": "Slowest calls"}]
        return [{"mark": "link", "from": min(mark["x"] for mark in found), "to": slowest[model], "tone": "quiet"}, *found]

    timed = sorted((model for model in models if median.get(model) and slowest.get(model)), key=lambda model: median[model])
    seconds = [mark["x"] for model in timed for mark in marks(model)[1:]]
    return [timed and {
        "id": "wait", "kind": "rows", "title": "How long a reader waits, and how long the tail runs",
        "how": "A row per model, the quickest median call first. The dot is the median time to the first token, a "
               "reasoning token included; the ring estimates when the first token a reader sees came, so the gap "
               "between them is reasoning. The tall tick is the median call, and the line runs on to the slow call, "
               "the 90th percentile, and the slowest calls, the 99th. Each mark is a median or a percentile of its "
               "own, not one call cut into parts. A dot on its tall tick is a host that sends its reply in one piece.",
        "values": "Its values are six of the numbers on this page. A row opens its model's card below.",
        # A slow model's tail can be a hundred times another's first token: on a scale of ratios both stay readable.
        "x": {"label": "Seconds", "unit": "seconds", "log": True} if max(seconds) >= 10 * min(seconds) else {"label": "Seconds", "unit": "seconds", "zero": True},
        "legend": [{"mark": "dot", "tone": "ink", "label": "Median time to first token"}, {"mark": "ring", "tone": "ink", "label": "First visible token, estimated"},
                   {"mark": "tick", "tone": "ink", "label": "Median call"}, {"mark": "tick", "tone": "quiet", "label": "Slow and slowest calls"}],
        "rows": [{"label": _short(model), "opens": model, "marks": marks(model)} for model in timed]}]


def _stability(by: dict[str, Any], results: list[Any], models: list[str]) -> list[dict[str, Any] | None]:
    cells: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for one in results:
        if one.clean is not None:
            cells[one.case if one.variant is None else f"{one.case} · {one.variant}", one.model].append(one.clean)
    cases = sorted({case for case, _ in cells})
    return [cases and {
        "id": "repeats", "kind": "grid", "title": "Each case, by the repeats each model passed",
        "how": "A cell per case and model. A quiet cell passed every repeat. A filled one did not, and says how many "
               "it passed: the request was the same each time, so the difference is the model's.",
        "values": "Each filled cell is a row of the table at the foot of this page. Every other cell passed all of its repeats.",
        "columns": [_short(model) for model in models],
        "legend": [{"mark": "dot", "tone": "quiet", "label": "Passed in every repeat"},
                   {"mark": "cell", "tone": "accent", "label": "Failed in at least one, with the repeats it passed"}],
        "rows": [{"label": case, "cells": [{"value": sum(cells[case, model]), "of": len(cells[case, model])} if (case, model) in cells else None
                                           for model in models]} for case in cases]}]


def _grounding(by: dict[str, Any], results: list[Any], models: list[str]) -> list[dict[str, Any] | None]:
    cited = _values(by["grounding"], "cited_of_sent")
    rows = [{"label": _short(model), "marks": [{"mark": "bar", "x": cited[model], "tone": "ink", "name": "Articles cited, of those sent"}]}
            for model in models if cited.get(model) is not None]
    return [rows and {
        "id": "cited", "kind": "rows", "title": "How much of what it was sent each model cited",
        "how": "Across the answers whose request carried knowledge: the articles an answer cites that its request "
               "carried, over the articles it carried.",
        "values": "Its values are a column of the table on this page.",
        "x": {"label": "Articles cited, of those sent", "unit": "percent", "zero": True, "to": 1}, "legend": [], "rows": rows}]


def _before_after(by: dict[str, Any], results: list[Any], models: list[str]) -> list[dict[str, Any] | None]:
    table = [row for row in _rows(by["before-after"], "by_case") if row["prompt_before"] is not None and row["prompt_after"] is not None]
    return [{
        "id": f"prompt-{case.split('/')[-1]}", "kind": "rows", "title": f"{case}: prompt tokens, before and after",
        "how": "Each model's count of the two requests for this question: the ring is before.py's, built by hand, and "
               "the dot is after.py's, built through CWA. A dot to the right of its ring is a request CWA made larger.",
        "values": "Its values are in the table of questions on this page.",
        "x": {"label": "Prompt tokens, by the model's own count", "unit": "tokens", "zero": True},
        "legend": [{"mark": "ring", "tone": "ink", "label": "before.py, by hand"}, {"mark": "dot", "tone": "ink", "label": "after.py, through CWA"}],
        "rows": [{"label": _short(row["model"]), "marks": [
            {"mark": "link", "from": row["prompt_before"], "to": row["prompt_after"], "tone": "quiet"},
            {"mark": "ring", "x": row["prompt_before"], "tone": "ink", "name": "before.py, by hand"},
            {"mark": "dot", "x": row["prompt_after"], "tone": "ink", "name": "after.py, through CWA"}]} for row in table if row["case"] == case]}
        for case in sorted({row["case"] for row in table})]


def _agents(by: dict[str, Any], results: list[Any], models: list[str]) -> list[dict[str, Any] | None]:
    budgets = sorted({one.budget for one in results if one.case.split("/")[0] not in SAME_CONTEXT and one.estimates and one.budget})
    drawn = [{"label": _short(row["model"]), "points": [[int(n), count] for n, count in row.items() if n != "model" and count is not None]}
             for row in _rows(by["agents"], "growth")]
    return [drawn and {
        "id": "growth", "kind": "lines", "title": "How an agent's request grows, inference by inference",
        "how": "A line per model: the assembler's count at each inference of a 04 or 05 task, the median across the "
               "tasks that reached it. Each tool result is an item in the next snapshot. The accent line is the "
               "route's budget.input, where fitting would start to shed.",
        "values": "Its values are in the last table on this page.",
        "x": {"label": "Inference", "unit": "count"}, "y": {"label": "The assembler's count", "unit": "tokens", "zero": True},
        "rules": [{"label": "The route's budget.input", "y": budgets[0], "tone": "accent"}] if len(budgets) == 1 else [],
        "series": drawn}]


def _checks(by: dict[str, Any], results: list[Any], models: list[str]) -> list[dict[str, Any] | None]:
    number = next(one for one in by["checks"]["numbers"] if one["id"] == "checks_passed")
    ranges = number.get("ranges") or {}
    rows = [{"label": _short(model), "marks": [
        *([{"mark": "range", "from": ranges[model][0], "to": ranges[model][1], "tone": "quiet", "name": "Where the rate could lie"}] if ranges.get(model) else []),
        {"mark": "dot", "x": number["values"][model], "tone": "ink", "name": "Checks passed"}]}
        for model in models if number["values"].get(model) is not None]
    return [rows and {
        "id": "passed", "kind": "rows", "title": "Checks passed, with the range each rate could have",
        "how": "The dot is the share of graded checks a model passed. The line is where that rate could lie over many "
               "more runs, 19 times in 20. Where two models' lines overlap, this run does not tell them apart.",
        "values": "Its values are the first column of the table on this page, with the range under each.",
        "x": {"label": "Checks passed", "unit": "percent", "zero": False, "to": 1},
        "legend": [{"mark": "dot", "tone": "ink", "label": "Checks passed"}, {"mark": "range", "tone": "quiet", "label": "Where the rate could lie"}],
        "rows": rows}]


CHARTS = {"decisions": _decisions, "tokens": _tokens, "cost": _cost, "speed": _speed, "stability": _stability,
          "grounding": _grounding, "before-after": _before_after, "agents": _agents, "checks": _checks}


def _values(page: dict[str, Any], id: str) -> dict[str, Any]:
    return next(one for one in page["numbers"] if one["id"] == id)["values"]


def _rows(page: dict[str, Any], id: str) -> list[dict[str, Any]]:
    return next(one for one in page["tables"] if one["id"] == id)["rows"]


def _short(model: str) -> str:
    return model.split("/")[-1]

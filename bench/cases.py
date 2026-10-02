"""What each example runs: a case per committed scenario, and how many model calls it likely makes and at most.

The counts come from the committed files. In 01-03 the context does not depend on the model, so a committed trace
says what will be sent, and a refused one that nothing will. In 04 and 05 each model's tool calls decide how many
inferences a question takes, so the committed recordings give a likely count and the agent's turn limit the most.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from config import ROOT


@dataclass(frozen=True)
class Budget:
    """Per call, at most: CWA never sends more input than the budget, nor asks for more output than it reserves."""
    input: int
    reserved_output: int


@dataclass(frozen=True)
class Case:
    example: str
    name: str               # its folder under the example's results, such as 01-answer/after
    args: tuple[str, ...]   # the example's script and its arguments, before the model and the output folder
    output: str             # the flag that names the output folder: --record, or --out for 05's suite
    tools: bool             # it sends tool definitions, so the model must take them
    calls: int              # model calls, likely
    most_calls: int         # model calls, at most
    input_tokens: int       # input tokens per call, likely
    budget: Budget


def cases(example: str) -> list[Case]:
    build = {"01-docs-qa": _docs_qa, "02-account-aware": _account_aware, "03-budget-and-routes": _budget_and_routes,
             "04-tools": _tools, "05-production": _production}[example]
    return build(ROOT / example)


def _docs_qa(folder: Path) -> list[Case]:
    found = []
    for scenario, trace in _scenarios(folder):
        conversation = ("--conversation", f"scenarios/{scenario}/conversation.json")
        found.append(_assembled(folder.name, f"{scenario}/after", ("after.py", *conversation), trace))
        # before.py sends every question and has no budget of its own; its estimate takes after.py's.
        budget = _budget(trace["budget"])
        found.append(Case(folder.name, f"{scenario}/before", ("before.py", *conversation), "--record", False,
                          1, 1, budget.input, budget))
    return found


def _account_aware(folder: Path) -> list[Case]:
    return [_assembled(folder.name, scenario, ("app.py", "--conversation", f"scenarios/{scenario}/conversation.json"),
                       trace) for scenario, trace in _scenarios(folder)]


def _budget_and_routes(folder: Path) -> list[Case]:
    routes = _read(folder / "policy" / "routes.json")
    found = []
    for scenario, trace in _scenarios(folder):
        args = ("app.py", "--conversation", f"scenarios/{scenario}/conversation.json")
        route = _read(folder / "scenarios" / scenario / "conversation.json").get("route") or routes["default"]
        escalates_to = routes["routes"][route]["escalate"].get((trace["refused"] or {}).get("reason") or "")
        if trace["result"] is None and escalates_to:
            # The app rebuilds the snapshot on the route the refusal names, and that route's model answers.
            budget = _budget(routes["routes"][escalates_to]["budget"])
            found.append(Case(folder.name, scenario, args, "--record", False, 1, 1, budget.input, budget))
        else:
            found.append(_assembled(folder.name, scenario, args, trace))
    return found


def _tools(folder: Path) -> list[Case]:
    found = []
    for path in sorted((folder / "scenarios").glob("*/scenario.json")):
        scenario = _read(path)
        traces = [_read(turn / "trace.json") for turn in sorted(path.parent.glob("turn-*"))]
        faults = tuple(arg for fault in scenario["faults"] for arg in ("--fault", fault))
        found.append(Case(folder.name, path.parent.name,
                          ("agent.py", scenario["question"], "--user", scenario["user"], *faults), "--record", True,
                          len(traces), _turn_limit(folder), _mean_input(traces), _budget(traces[0]["budget"])))
    return found


def _production(folder: Path) -> list[Case]:
    suite = _read(folder / "evals" / "cases.json")["cases"]
    recordings = sorted(path.parent for path in (folder / "evals" / "results").glob("*/meta.json"))
    # Per case, the inferences the committed recordings took, on average.
    calls = sum(mean(len(list((recording / case["id"]).glob("turn-*"))) for recording in recordings) if recordings
                else 1 for case in suite)
    traces = [_read(path) for recording in recordings for path in recording.glob("*/turn-*/trace.json")]
    routes = _read(folder / "policy" / "routes.json")
    budget = _budget(routes["routes"][routes["default"]]["budget"])
    return [Case(folder.name, "evals", ("evals.py", "run"), "--out", True, round(calls),
                 len(suite) * _turn_limit(folder), _mean_input(traces) if traces else budget.input, budget)]


def _assembled(example: str, name: str, args: tuple[str, ...], trace: dict[str, Any]) -> Case:
    """A single assembly: one call with what the trace says was sent, or none when it refused."""
    sent = trace["result"] is not None
    return Case(example, name, args, "--record", False, int(sent), int(sent),
                trace["result"]["input_tokens"] if sent else 0, _budget(trace["budget"]))


def _scenarios(folder: Path) -> list[tuple[str, dict[str, Any]]]:
    return [(path.parent.name, _read(path)) for path in sorted((folder / "scenarios").glob("*/trace.json"))]


def _turn_limit(folder: Path) -> int:
    return int(re.search(r"^MAX_TURNS = (\d+)", (folder / "agent.py").read_text(encoding="utf-8"), re.M).group(1))


def _mean_input(traces: list[dict[str, Any]]) -> int:
    return round(mean(trace["result"]["input_tokens"] for trace in traces if trace["result"]))


def _budget(budget: dict[str, Any]) -> Budget:
    return Budget(input=budget["input"], reserved_output=budget["reserved_output"])


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

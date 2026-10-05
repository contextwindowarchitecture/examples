"""A run's numbers, for the viewer's "See the numbers" pages. Everything is read from the run's folder; nothing calls
a model.

    facts    one row per answered call, joined to the assembly whose payload it carried, and one per result
    write    numbers.json, which grade.py writes beside summary.json: the run's models and its pages
    pages    each a list of numbers, one value per model with the formula behind it, and tables that break them down:
             tokens   what the same context costs in each model's own tokens, and the margin a route would need
             cost     what was charged against the list price, the factors it comes from, and what it bought
             speed    how long a call takes, split into what waits and what each output token takes
             stability   what repeats of the same case agree on: the checks, the answer's words, the tool calls

The checks say whether an answer passed. The numbers say what the same context cost each model in tokens, dollars and
seconds, how much its answers moved between repeats, and how far the checks tell the models apart.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations
from math import ceil
from pathlib import Path
from statistics import mean, median
from typing import Any

import checks
from config import ROOT

# 01-03 send every model the same payloads (same_context), so what differs there is the model's or its host's.
SAME_CONTEXT = ("01-docs-qa", "02-account-aware", "03-budget-and-routes")


@dataclass(frozen=True)
class Call:
    """One answered call. before.py builds its request by hand, so its call carries no assembly."""
    job: str
    model: str
    example: str
    task: str                     # the case it worked on, as the summary's results name it: in 05, the eval case
    variant: str | None           # 01's after or before
    repeat: int
    prompt: int                   # tokens as the host counted them
    completion: int
    reasoning: int
    cached: int
    cost: float
    ms: int
    host: str | None
    attempts: int
    finish: str | None
    prompt_cost: float | None     # what the host charged for each side, when it says
    completion_cost: float | None
    assembly: str | None          # record, a route's name, or turn-<n>
    estimate: int | None          # tokens as the assembler counted the payload (trace.result.input_tokens)
    budget: int | None            # the route's budget.input
    margin: int | None            # and its margin_percent


@dataclass(frozen=True)
class Result:
    """One case one model ran to the end: its graded checks, its answer, and for an agent its tool calls."""
    job: str
    model: str
    case: str
    variant: str | None
    repeat: int
    checks: tuple[tuple[str, bool], ...]  # each graded check about the model, by "measure check", and whether it passed
    answer: str | None
    cited: tuple[str, ...]
    left_out: tuple[str, ...]             # before.py: what it cited that the committed assembly left out
    steps: tuple[tuple[str, bool], ...]   # each tool call tried, and whether the guard approved it
    estimates: tuple[int, ...]            # the assembler's count at each inference that sent

    @property
    def clean(self) -> bool | None:
        """Every graded check passed. None when nothing was graded, as when the assembly refused."""
        return all(passed for _, passed in self.checks) if self.checks else None


def facts(run: Path, summary: dict[str, Any]) -> tuple[list[Call], list[Result]]:
    """summary: the run's summary.json (summary.py), which names every job and result."""
    lines: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if (run / "calls.jsonl").exists():
        for line in (run / "calls.jsonl").read_text(encoding="utf-8").splitlines():
            lines[json.loads(line)["job"]].append(json.loads(line))
    calls = [call for job in summary["jobs"] if job["exit"] is not None
             for call in _calls(run / job["job"], job, checks.last_attempt(lines[job["job"]]))]
    return calls, [_result(run, result) for result in summary["results"] if result["exit"] == 0]


def _calls(folder: Path, job: dict[str, Any], lines: list[dict[str, Any]]) -> list[Call]:
    answered = [line for line in lines if line["status"] == 200 and not line.get("error")]
    # The join payload_sent checks: a job's answered calls, in order, carried its rendered payloads, in order.
    sent = [path for path in checks.assembled(job["example"], folder / "record") if (path / "payload.json").exists()]
    joined = sent if job["exit"] == 0 and len(sent) == len(answered) else [None] * len(answered)
    scenario, _, variant = job["case"].partition("/")
    found = []
    for line, assembly in zip(answered, joined):
        trace = _read(assembly / "trace.json") if assembly else None
        response = folder / "calls" / f"{line['call']}.response.json"
        said = _read(response) if response.exists() else {}
        charged = (said.get("usage") or {}).get("cost_details") or {}
        tokens = line.get("tokens") or {}
        in_suite = assembly is not None and job["example"] == "05-production"
        found.append(Call(
            job=job["job"], model=job["model"], example=job["example"],
            task=f"{job['example']}/{assembly.parent.name if in_suite else scenario}", variant=variant or None,
            repeat=job["repeat"], prompt=tokens.get("prompt") or 0, completion=tokens.get("completion") or 0,
            reasoning=tokens.get("reasoning") or 0, cached=tokens.get("cached") or 0, cost=line.get("cost") or 0,
            ms=line["ms"], host=line.get("host"), attempts=len(line.get("attempts") or []),
            finish=((said.get("choices") or [{}])[0]).get("finish_reason"),
            prompt_cost=charged.get("upstream_inference_prompt_cost"),
            completion_cost=charged.get("upstream_inference_completions_cost"),
            assembly=assembly.name if assembly else None,
            estimate=trace["result"]["input_tokens"] if trace else None,
            budget=trace["budget"]["input"] if trace else None,
            margin=trace["budget"].get("margin_percent") if trace else None))
    return found


def _result(run: Path, result: dict[str, Any]) -> Result:
    answered = _read(run / result["answer"]) if result["answer"] else {}
    answer = answered.get("answer")
    cited = tuple(sorted(set(checks.CITATION.findall((answer or "").translate(checks.TYPOGRAPHY)))))
    left_out: tuple[str, ...] = ()
    if result["request"]:  # before.py's run: it records the request it built, and no trace
        example, scenario = result["case"].split("/", 1)
        excluded = {row["item_id"] for row in _read(ROOT / example / "scenarios" / scenario / "trace.json")["excluded"]}
        left_out = tuple(citation for citation in cited if citation in excluded)
    traces = [_read(run / assembly / "trace.json") for assembly in result["assemblies"]]
    return Result(
        job=result["job"], model=result["model"], case=result["case"], variant=result["variant"], repeat=result["repeat"],
        checks=tuple((f"{check['measure']} {check['check']}", check["passed"]) for check in result["checks"]
                     if check["passed"] is not None and check["measure"] not in ("invariant", "run")),
        answer=answer, cited=cited, left_out=left_out,
        steps=tuple((step["tool"], step["approved"]) for step in answered.get("steps", [])),
        estimates=tuple(trace["result"]["input_tokens"] for trace in traces if trace["result"]))


def write(run: Path, summary: dict[str, Any]) -> dict[str, Any]:
    """The run's numbers.json, which the viewer's "See the numbers" pages read. summary: its summary.json."""
    calls, results = facts(run, summary)
    models = list(summary["models"])
    pasted = frozenset(case["key"] for case in summary["cases"] if len(case["question"].strip().splitlines()) > 1)
    pages = [tokens(calls, models, pasted), cost(calls, results, summary), speed(calls, summary), stability(results, models)]
    written = {"run": summary["run"], "graded": summary["graded"], "models": models, "pages": pages}
    (run / "numbers.json").write_text(json.dumps(written, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return written


# The arithmetic

def line(points: Iterable[tuple[float, float]]) -> tuple[float, float] | None:
    """The line through points, as where it starts and its slope: the median slope between pairs of points, then the
    median of what that leaves (Theil-Sen), so a point off the others does not move it. None when no two differ in x."""
    points = list(points)
    slopes = [(y2 - y1) / (x2 - x1) for (x1, y1), (x2, y2) in combinations(points, 2) if x1 != x2]
    if not slopes:
        return None
    slope = median(slopes)
    return median(y - slope * x for x, y in points), slope


def percentile(found: Iterable[float], rank: float) -> float | None:
    """The value at a rank out of 100, by nearest rank, so it is always one that was observed."""
    ordered = sorted(found)
    return ordered[max(ceil(rank / 100 * len(ordered)), 1) - 1] if ordered else None


def jaccard(one: str, other: str) -> float:
    """How much two answers share: the words in both over the words in either, whatever their case and order."""
    first, second = set(one.lower().split()), set(other.lower().split())
    return len(first & second) / len(first | second) if first | second else 1


# Pages

def tokens(calls: list[Call], models: list[str], pasted: frozenset[str] = frozenset()) -> dict[str, Any]:
    """pasted: the cases whose question pastes a block of text, such as 03's delivery log. A tokenizer counts a log
    unlike prose, so the line is drawn through the other requests, and a pasted block gets a rate of its own."""
    counted = [call for call in calls if call.estimate]  # the calls that carried an assembled payload
    same = [call for call in counted if call.example in SAME_CONTEXT]
    task = {_case(call): call.task for call in same}
    first = {case: next(call for call in same if _case(call) == case) for case in sorted(task)}
    here = lambda case, model: [call for call in _of(same, model) if _case(call) == case]
    # Each request once per model: the assembler's estimate, and the median of what the host counted across repeats.
    requests = {model: {case: (first[case].estimate, median(call.prompt for call in here(case, model)))
                        for case in first if here(case, model)} for model in models}
    fits = {model: line(point for case, point in requests[model].items() if task[case] not in pasted) for model in models}
    on_pasted = {model: _mean((count - fits[model][0]) / estimate for case, (estimate, count) in requests[model].items()
                              if task[case] in pasted) if fits[model] else None for model in models}
    # R-16: a payload fits when its count times (100 + margin_percent) / 100, rounded up, is within budget.input.
    covered = lambda call: (call.estimate * (100 + (call.margin or 0)) + 99) // 100 >= call.prompt
    tasks: dict[tuple[str, str, str], list[Call]] = defaultdict(list)
    for call in calls:
        if call.example not in SAME_CONTEXT:
            tasks[call.model, call.job, call.task].append(call)
    resent = {key: sum(call.prompt for call in found) / found[-1].prompt for key, found in tasks.items() if len(found) > 1}
    return {"id": "tokens", "title": "Tokens", "lede": (
        "What the same context costs in each model's own tokens. The assembler counts a payload with the tokenizer its "
        "route declares, an estimate in every example, and fits it to the route's budget.input with a margin for the "
        "estimate's error (R-16). The host then counts the request its own way. In 01–03 every model is sent the same "
        "payloads, so the two counts can be set side by side."),
        "numbers": [
            _number("tokens_per_estimated", "Tokens per estimated token", "ratio",
                    "The slope of the line through a model's 01–03 requests: the tokens its host counted against the "
                    "assembler's estimate. It is the median slope between pairs of requests, so one that counts "
                    "differently does not move it. Requests whose question pastes a block of text are left off the line.",
                    {model: fits[model] and fits[model][1] for model in models},
                    {model: sum(task[case] not in pasted for case in requests[model]) for model in models}),
            _number("tokens_added", "Tokens added to every request", "tokens",
                    "Where that line starts: what the host counts whatever the payload holds, such as a system prompt "
                    "of its own. A percentage margin cannot cover it; an application subtracts it from budget.input.",
                    {model: fits[model] and fits[model][0] for model in models}),
            _number("tokens_per_estimated_pasted", "Tokens per estimated token, pasted text", "ratio",
                    "For the requests whose question pastes a block of text, such as a log: the host's count less the "
                    "tokens added to every request, over the estimate. An estimate from bytes runs low on digits and "
                    "punctuation.",
                    on_pasted, {model: sum(task[case] in pasted for case in requests[model]) for model in models}),
            _number("margin_needed", "Margin needed", "percent",
                    "The smallest budget.margin_percent that would have covered every 01–03 request: the largest host "
                    "count over its estimate, less one. The table below sets it against the margin each route declares.",
                    {model: max((max(call.prompt / call.estimate - 1, 0) for call in _of(same, model)), default=None)
                     for model in models}, _count(same, models)),
            _number("margin_covered", "Requests the declared margin covered", "percent",
                    "Of a model's 01–03 calls, those whose host count is within the estimate plus the route's declared "
                    "margin_percent.",
                    {model: _share(covered(call) for call in _of(same, model)) for model in models}, _count(same, models)),
            _number("over_budget", "Calls over the route's budget", "count",
                    "Calls whose host count is more than the route's budget.input, 04 and 05 included. The assembler "
                    "fitted each to that budget by its own count.",
                    {model: sum(call.prompt > call.budget for call in _of(counted, model)) if _of(counted, model) else None
                     for model in models}, _count(counted, models)),
            _number("cached_share", "Prompt tokens read from cache", "percent",
                    "Cached prompt tokens over prompt tokens, across every call. Hosts bill cached tokens for less.",
                    {model: _ratio(sum(call.cached for call in _of(calls, model)), sum(call.prompt for call in _of(calls, model)))
                     for model in models}),
            _number("resend_factor", "Tokens sent per token of final request", "ratio",
                    "An agent sends its context again at every inference. For each 04–05 task with more than one: the "
                    "prompt tokens of all its inferences over those of its last, then the mean across tasks.",
                    {model: _mean(factor for (owner, _, _), factor in resent.items() if owner == model) for model in models},
                    {model: sum(owner == model for owner, _, _ in resent) for model in models}),
        ],
        "tables": [
            _table("by_case", "The same request, counted by each model",
                   "Each 01–03 request: the assembler's estimate, the route's budget.input and how much of it the "
                   "estimate uses, then the tokens each model's host counted, the median across repeats.",
                   [_column("case", "Request"), _column("question", "Question"), _column("estimate", "Estimate", "tokens"),
                    _column("budget", "Budget", "tokens"), _column("used", "Used", "percent"),
                    *(_column(model, _short(model), "tokens") for model in models)],
                   [{"case": case, "question": "pastes a block" if task[case] in pasted else "one line",
                     "estimate": call.estimate, "budget": call.budget, "used": _r(call.estimate / call.budget),
                     **{model: requests[model].get(case, (None, None))[1] for model in models}} for case, call in first.items()]),
            _table("margin_by_case", "The margin each request needed",
                   "Each 01–03 request: the margin its route declares, then for each model the host's count over the "
                   "estimate, less one. A request is covered when that is within the declared margin.",
                   [_column("case", "Request"), _column("declared", "Declared", "percent"),
                    *(_column(model, _short(model), "percent") for model in models)],
                   [{"case": case, "declared": (call.margin or 0) / 100,
                     **{model: _r(requests[model][case][1] / call.estimate - 1) if case in requests[model] else None
                        for model in models}} for case, call in first.items()]),
        ]}


def cost(calls: list[Call], results: list[Result], summary: dict[str, Any]) -> dict[str, Any]:
    """summary: for each model's list prices and what the run spent on it, and each job's cost."""
    listed = summary["models"]
    models = list(listed)
    total = lambda model, field: sum(getattr(call, field) for call in _of(calls, model))
    at_list = {model: total(model, "prompt") * listed[model]["input_price"] + total(model, "completion") * listed[model]["output_price"]
               for model in models}
    split = {model: [call for call in _of(calls, model) if call.prompt_cost is not None and call.completion_cost is not None]
             for model in models}
    passed = {model: sum(ok for one in _of(results, model) for _, ok in one.checks) for model in models}
    clean = {model: sum(one.clean is True for one in _of(results, model)) for model in models}
    examples = sorted({job["example"] for job in summary["jobs"] if job["exit"] == 0})
    return {"id": "cost", "title": "Cost", "lede": (
        "What each model was charged, and where the charge comes from. A call costs its prompt tokens at the input "
        "price, less what the host takes off for tokens read from cache, plus its completion tokens, reasoning "
        "included, at the output price. Every factor is in the table below, so a gap between two models can be read "
        "as the factors that differ."),
        "numbers": [
            _number("spend", "Spent", "usd", "What OpenRouter charged for every call, an attempt that failed included.",
                    {model: listed[model]["cost"] for model in models}),
            _number("charged_over_list", "Charged over list price", "ratio",
                    "What was charged for a model's answered calls over their tokens at the prices OpenRouter listed "
                    "when the run was planned. Below one, a host discounted, as for cached tokens; above it, the host "
                    "that answered charges more than the listing.",
                    {model: _ratio(total(model, "cost"), at_list[model]) for model in models}),
            _number("prompt_share_of_spend", "Share of the charge that is prompt", "percent",
                    "What hosts charged for prompts over what they charged in all, for the calls whose host says.",
                    {model: _ratio(sum(call.prompt_cost for call in split[model]),
                                   sum(call.prompt_cost + call.completion_cost for call in split[model])) for model in models},
                    {model: len(split[model]) for model in models}),
            _number("cost_per_passed_check", "Cost per check passed", "usd",
                    "Spent over the graded checks the model's answers passed.",
                    {model: _ratio(listed[model]["cost"], passed[model]) for model in models}, passed),
            _number("cost_per_clean_result", "Cost per result with every check passed", "usd",
                    "Spent over the results in which every graded check passed.",
                    {model: _ratio(listed[model]["cost"], clean[model]) for model in models}, clean),
        ],
        "tables": [
            _table("identity", "Where the charge comes from",
                   "For a model's answered calls: prompt tokens at the input price, less the discount on the share "
                   "read from cache, plus completion tokens at the output price. Prices are per million tokens.",
                   [_column("model", "Model"), _column("calls", "Calls", "count"), _column("prompt", "Prompt tokens", "tokens"),
                    _column("input_price", "Input price", "usd"), _column("cached", "Cached", "percent"),
                    _column("completion", "Completion tokens", "tokens"), _column("reasoning", "Reasoning", "percent"),
                    _column("output_price", "Output price", "usd"), _column("list", "At list price", "usd"),
                    _column("charged", "Charged", "usd")],
                   [{"model": model, "calls": len(_of(calls, model)), "prompt": total(model, "prompt"),
                     "input_price": _r(listed[model]["input_price"] * 1e6),
                     "cached": _r(_ratio(total(model, "cached"), total(model, "prompt"))),
                     "completion": total(model, "completion"),
                     "reasoning": _r(_ratio(total(model, "reasoning"), total(model, "completion"))),
                     "output_price": _r(listed[model]["output_price"] * 1e6), "list": _r(at_list[model]),
                     "charged": _r(total(model, "cost"))} for model in models]),
            _table("by_example", "A job's cost, by example",
                   "The median cost of a job that ran to the end: one case for 01–04, the whole suite for 05.",
                   [_column("example", "Example"), *(_column(model, _short(model), "usd") for model in models)],
                   [{"example": example, **{model: _r(_median(job["cost"] for job in summary["jobs"] if job["exit"] == 0
                                                             and (job["model"], job["example"]) == (model, example)))
                                            for model in models}} for example in examples]),
        ]}


def speed(calls: list[Call], summary: dict[str, Any]) -> dict[str, Any]:
    models = list(summary["models"])
    timed = lambda model: [call for call in _of(calls, model) if call.ms and call.completion]
    fits = {model: line((call.completion, call.ms) for call in timed(model)) for model in models}
    at = lambda rank: {model: _scaled(percentile((call.ms for call in _of(calls, model)), rank), 1 / 1000) for model in models}
    done = [job for job in summary["jobs"] if job["exit"] == 0 and job.get("seconds") is not None]
    hosts = sorted({(call.model, call.host) for call in calls if call.host}, key=lambda pair: (models.index(pair[0]), pair[1]))
    return {"id": "speed", "title": "Speed", "lede": (
        "How long a call took, start to finish, as the proxy timed it. The examples do not stream, so there is no time "
        "to a first token: a line through each model's calls, time against output tokens, splits a call into what "
        "waits and what each token takes. Reasoning tokens take time and are billed, and the reader never sees them."),
        "numbers": [
            _number("seconds_p50", "Median call", "seconds", "The middle call, by nearest rank.", at(50), _count(calls, models)),
            _number("seconds_p90", "Slow call", "seconds", "The call 90% were faster than or equal to.", at(90)),
            _number("seconds_p99", "Slowest calls", "seconds", "The call 99% were faster than or equal to.", at(99)),
            _number("tokens_per_second", "Output tokens a second", "per_second",
                    "The median, across calls, of completion tokens over the call's seconds. The wait is in it, so "
                    "short answers look slower.",
                    {model: _median(call.completion / call.ms * 1000 for call in timed(model)) for model in models}),
            _number("visible_per_second", "Visible tokens a second", "per_second",
                    "The same for the tokens the reader sees: completion tokens less reasoning tokens.",
                    {model: _median((call.completion - call.reasoning) / call.ms * 1000 for call in timed(model)) for model in models}),
            _number("reasoning_share", "Output that is reasoning", "percent",
                    "Reasoning tokens over completion tokens, across every call.",
                    {model: _ratio(sum(call.reasoning for call in _of(calls, model)), sum(call.completion for call in _of(calls, model)))
                     for model in models}),
            _number("seconds_fixed", "Seconds whatever the output", "seconds",
                    "Where the line through a model's calls starts, milliseconds against completion tokens: the "
                    "median slope between pairs of calls, then the median of what is left.",
                    {model: _scaled(fits[model] and fits[model][0], 1 / 1000) for model in models}),
            _number("ms_per_token", "Milliseconds per output token", "ms", "That line's slope.",
                    {model: fits[model] and fits[model][1] for model in models}),
            _number("retried", "Calls tried more than once", "count",
                    "Calls the proxy sent again after a 429, a 5xx or a dropped connection, and that were then answered.",
                    {model: sum(call.attempts > 1 for call in _of(calls, model)) for model in models}),
            _number("cut_short", "Answers cut short", "count",
                    "Calls that ended because the output ran out: finish_reason length.",
                    {model: sum(call.finish == "length" for call in _of(calls, model)) for model in models}),
        ],
        "tables": [
            _table("seconds_by_example", "A job's seconds, by example",
                   "The median time of a job that ran to the end, from starting the example's command to its exit: one "
                   "case for 01–04, the whole suite for 05.",
                   [_column("example", "Example"), *(_column(model, _short(model), "seconds") for model in models)],
                   [{"example": example, **{model: _r(_median(job["seconds"] for job in done if (job["model"], job["example"]) == (model, example)))
                                            for model in models}} for example in sorted({job["example"] for job in done})]),
            _table("by_host", "Calls by the host that answered",
                   "OpenRouter may serve a model from several hosts. For each: its calls, its share of the model's, "
                   "and its median call.",
                   [_column("model", "Model"), _column("host", "Host"), _column("calls", "Calls", "count"),
                    _column("share", "Share", "percent"), _column("seconds", "Median call", "seconds")],
                   [{"model": model, "host": host, "calls": len(found := [call for call in _of(calls, model) if call.host == host]),
                     "share": _r(len(found) / len(_of(calls, model))), "seconds": _r(median(call.ms for call in found) / 1000)}
                    for model, host in hosts]),
        ]}


def stability(results: list[Result], models: list[str]) -> dict[str, Any]:
    cells = _cells(results)
    repeated = {key: found for key, found in cells.items() if len(found) > 1}
    # A cell's verdicts, when it was graded more than once: a refused assembly sends nothing, so nothing is graded.
    verdicts = {key: flags for key, found in repeated.items() if len(flags := [one.clean for one in found if one.clean is not None]) > 1}
    same_context = lambda key: key[1].split("/")[0] in SAME_CONTEXT
    answers = {key: texts for key, found in repeated.items()
               if same_context(key) and len(texts := [one.answer for one in found if one.answer]) > 1}
    alike = {key: mean(jaccard(one, other) for one, other in combinations(texts, 2)) for key, texts in answers.items()}
    cites = {key: len({one.cited for one in found if one.answer}) == 1 for key, found in repeated.items() if key in answers}
    paths = {key: len({one.steps for one in found}) == 1 for key, found in repeated.items() if not same_context(key)}
    mine = lambda found, model: [value for key, value in found.items() if key[0] == model]
    graded = [one for one in results if one.clean is not None]
    return {"id": "stability", "title": "Stability", "lede": (
        "What repeats of the same case agree on. In 01–03 every repeat sends the same request, so what moves is the "
        "model: whether its answer passes, the words it uses and what it cites. In 04 and 05 the model also chooses "
        "its tool calls. A check passed once says less than a check passed every time."),
        "numbers": [
            _number("pass_average", "Results with every check passed", "percent",
                    "Of a model's graded results, those in which every graded check passed.",
                    {model: _share(one.clean for one in _of(graded, model)) for model in models}, _count(graded, models)),
            _number("pass_every", "Cases passed in every repeat", "percent",
                    "Of the cases a model was graded on more than once, those it passed in every repeat. It is at "
                    "most the average, and falls with more repeats when answers vary.",
                    {model: _share(all(flags) for flags in mine(verdicts, model)) for model in models},
                    {model: len(mine(verdicts, model)) for model in models}),
            _number("cases_some", "Cases passed in some repeats", "count",
                    "Cases whose result changed between repeats: passed in at least one, and not in all.",
                    {model: sum(any(flags) and not all(flags) for flags in mine(verdicts, model)) for model in models}),
            _number("cases_none", "Cases passed in no repeat", "count", "Cases with a failed check in every repeat.",
                    {model: sum(not any(flags) for flags in mine(verdicts, model)) for model in models}),
            _number("answer_similarity", "Words shared between repeats", "percent",
                    "For each 01–03 case answered more than once: the words two answers share over the words in "
                    "either, averaged over every pair of repeats, then over cases.",
                    {model: _mean(mine(alike, model)) for model in models}, {model: len(mine(alike, model)) for model in models}),
            _number("same_citations", "Cases cited the same way every repeat", "percent",
                    "Of those cases, the ones where every repeat cites the same articles.",
                    {model: _share(mine(cites, model)) for model in models}),
            _number("same_tool_path", "Tasks done the same way every repeat", "percent",
                    "Of the 04–05 cases run more than once, those where every repeat made the same tool calls in the "
                    "same order.",
                    {model: _share(mine(paths, model)) for model in models}, {model: len(mine(paths, model)) for model in models}),
        ],
        "tables": [
            _table("not_every_repeat", "Cases not passed in every repeat",
                   "Each case a model failed in at least one repeat: how many repeats it passed, and the checks that "
                   "failed, with how often.",
                   [_column("model", "Model"), _column("case", "Case"), _column("passed", "Repeats passed"), _column("checks", "Failed checks")],
                   [{"model": model, "case": case if variant is None else f"{case} · {variant}",
                     "passed": f"{sum(flags)} of {len(flags)}",
                     "checks": ", ".join(f"{name} ×{count}" for name, count in Counter(
                         name for one in repeated[model, case, variant] for name, passed in one.checks if not passed).items())}
                    for (model, case, variant), flags in verdicts.items() if not all(flags)]),
        ]}


def _cells(results: list[Result]) -> dict[tuple[str, str, str | None], list[Result]]:
    """A model's results for one case, and for 01 one of its two scripts, across repeats."""
    cells: dict[tuple[str, str, str | None], list[Result]] = defaultdict(list)
    for one in sorted(results, key=lambda one: one.repeat):
        cells[one.model, one.case, one.variant].append(one)
    return cells


def _case(call: Call) -> str:
    """A request's name: its case, and in 03 the route that sent it."""
    return call.task if call.assembly in (None, "record") else f"{call.task} · {call.assembly}"


def _of(found: list[Any], model: str) -> list[Any]:
    return [one for one in found if one.model == model]


def _number(id: str, label: str, unit: str, how: str, values: dict[str, Any], n: dict[str, int] | None = None) -> dict[str, Any]:
    """One value per model, with the formula behind it and, when it rests on a count of observations, that count."""
    return {"id": id, "label": label, "unit": unit, "how": how, "values": {model: _r(value) for model, value in values.items()},
            **({"n": n} if n is not None else {})}


def _table(id: str, title: str, how: str, columns: list[dict[str, str]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": id, "title": title, "how": how, "columns": columns, "rows": rows}


def _column(id: str, label: str, unit: str = "text") -> dict[str, str]:
    return {"id": id, "label": label, "unit": unit}


def _count(found: list[Any], models: list[str]) -> dict[str, int]:
    return {model: len(_of(found, model)) for model in models}


def _short(model: str) -> str:
    return model.split("/")[-1]


def _share(flags: Iterable[bool]) -> float | None:
    flags = list(flags)
    return sum(flags) / len(flags) if flags else None


def _ratio(part: float, whole: float) -> float | None:
    return part / whole if whole else None


def _scaled(value: float | None, by: float) -> float | None:
    return None if value is None else value * by


def _mean(found: Iterable[float]) -> float | None:
    found = list(found)
    return mean(found) if found else None


def _median(found: Iterable[float]) -> float | None:
    found = list(found)
    return median(found) if found else None


def _r(value: Any) -> Any:
    """A figure as numbers.json holds it: six decimal places, which a cost per check needs, and no negative zero."""
    return round(value, 6) + 0 if isinstance(value, float) else value


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

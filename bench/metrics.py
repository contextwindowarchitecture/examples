"""A run's numbers, for the viewer's "See the numbers" pages. Everything is read from the run's folder; nothing calls
a model.

    facts    one row per answered call, joined to the assembly whose payload it carried, and one per result
    write    numbers.json, which grade.py writes beside summary.json: the run's models and its pages
    pages    each a list of numbers, one value per model with the formula behind it, and tables that break them down:
             tokens   what the same context costs in each model's own tokens, and the margin a route would need
             cost     what was charged against the list price, the factors it comes from, and what it bought
             speed    how long a call takes: the wait for its first token, the generation, and what is outside both
             stability   what repeats of the same case agree on: the checks, the answer's words, the tool calls
             before_after   01's two requests for the same question, by hand and through CWA, and what changed
             agents   what 04 and 05's agents tried, what the guard refused, and how their context grew
             verdicts   the checks themselves: how sure a pass rate is, and how far the checks tell the models apart

The checks say whether an answer passed. The numbers say what the same context cost each model in tokens, dollars and
seconds, how much its answers moved between repeats, and how far the checks tell the models apart.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations
from math import ceil, sqrt
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
    first_token: int | None       # what OpenRouter recorded, when the run holds it (generations.py): milliseconds to the
    generating: int | None        # first token, milliseconds the generation took, the prompt's tokens by OpenRouter's
    normalized: int | None        # own count, which is the same for every model, and how many hosts it tried
    tried: int | None
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
        recorded = folder / "calls" / f"{line['call']}.generation.json"
        stats = _read(recorded) if recorded.exists() else {}
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
            first_token=stats.get("latency"), generating=stats.get("generation_time"), normalized=stats.get("tokens_prompt"),
            tried=len(stats["attempts"]) if stats.get("attempts") else None,
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
    pages = [tokens(calls, models, pasted, summary["models"]), cost(calls, results, summary), speed(calls, summary),
             stability(results, models, summary["models"]),
             before_after(calls, results, models), agents(results, models), verdicts(calls, results, models)]
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


def wilson(passed: int, graded: int) -> tuple[float, float] | None:
    """The range a rate seen as passed of graded could have over many more, 19 times in 20 (Wilson's score interval).
    It is wide when few were graded, and stays within 0 and 1."""
    if not graded:
        return None
    z = 1.96
    rate, room = passed / graded, z * z / graded
    spread = z * sqrt(rate * (1 - rate) / graded + room / (4 * graded))
    return (rate + room / 2 - spread) / (1 + room), (rate + room / 2 + spread) / (1 + room)


# Pages

def tokens(calls: list[Call], models: list[str], pasted: frozenset[str] = frozenset(),
           listed: dict[str, Any] | None = None) -> dict[str, Any]:
    """pasted: the cases whose question pastes a block of text, such as 03's delivery log. A tokenizer counts a log
    unlike prose, so the line is drawn through the other requests, and a pasted block gets a rate of its own.
    listed: each model as OpenRouter listed it when the run was planned."""
    fact = lambda model, name: ((listed or {}).get(model) or {}).get(name)
    largest = lambda model: max((call.budget for call in calls if call.model == model and call.budget), default=None)
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
        "totals": [
            {"id": "normalized_over_estimate", "label": "OpenRouter's count over the estimate", "unit": "ratio",
             "value": _r(_median(call.normalized / call.estimate for call in counted if call.normalized)),
             "how": "OpenRouter counts every request with one tokenizer of its own, whatever the model. The median, "
                    "across the run's calls, of that count over the assembler's estimate: how the estimate does "
                    "against a count that is the same for everyone."},
        ],
        "numbers": [
            _number("tokenizer", "Tokenizer", "text",
                    "The family of the model's own tokenizer, as OpenRouter listed it when the run was planned.",
                    {model: fact(model, "tokenizer") for model in models}),
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
            _number("context", "Context limit", "tokens", "The model's context limit, as OpenRouter listed it.",
                    {model: fact(model, "context") for model in models}),
            _number("budget_share", "Largest budget, of the context limit", "percent",
                    "The largest budget.input a route sent this model, over its context limit. R-16 sets budget.input "
                    "to the limit less the reserved output; the examples set far less, so no count here overflowed.",
                    {model: _ratio(largest(model), fact(model, "context") or 0) if largest(model) else None for model in models}),
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
                   "Each 01–03 request: the assembler's estimate, OpenRouter's count of the same request with its own "
                   "tokenizer, the route's budget.input and how much of it the estimate uses, then the tokens each "
                   "model's host counted, the median across repeats.",
                   [_column("case", "Request"), _column("question", "Question"), _column("estimate", "Estimate", "tokens"),
                    _column("normalized", "OpenRouter's count", "tokens"), _column("budget", "Budget", "tokens"), _column("used", "Used", "percent"),
                    *(_column(model, _short(model), "tokens") for model in models)],
                   [{"case": case, "question": "pastes a block" if task[case] in pasted else "one line",
                     "estimate": call.estimate, "normalized": _median(one.normalized for one in same if _case(one) == case and one.normalized),
                     "budget": call.budget, "used": _r(call.estimate / call.budget),
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
            _number("planned", "Planned, likely", "usd",
                    "What plan.py estimated before the run: the calls and input sizes of the committed files, and "
                    "1,000 output tokens a call, at the listed prices. Runs made before the manifest kept it show none.",
                    {model: (listed[model].get("planned") or {}).get("likely") for model in models}),
            _number("spent_over_planned", "Spent over planned", "ratio", "What was spent over that estimate.",
                    {model: _ratio(listed[model]["cost"], (listed[model].get("planned") or {}).get("likely") or 0) for model in models}),
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
    # The calls OpenRouter's stats split: to the first token, then generating, with the rest outside the generation.
    split = lambda model: [call for call in timed(model) if call.first_token is not None and call.generating]
    # Some hosts send a whole reply at once: its first token comes with its last, in the last tenth of the generation,
    # and says nothing of how fast the host generates.
    whole = lambda call: call.first_token >= 0.9 * call.generating
    flowing = lambda model: [call for call in split(model) if not whole(call)]
    at = lambda rank, field, found: {model: _scaled(percentile((getattr(call, field) for call in found(model)), rank), 1 / 1000) for model in models}
    everything = lambda model: _of(calls, model)
    done = [job for job in summary["jobs"] if job["exit"] == 0 and job.get("seconds") is not None]
    hosts = sorted({(call.model, call.host) for call in calls if call.host}, key=lambda pair: (models.index(pair[0]), pair[1]))
    return {"id": "speed", "title": "Speed", "lede": (
        "How long a call took. The proxy times each one from start to finish; the examples do not stream, so the time "
        "to the first token is the one OpenRouter recorded, which streams from the host whatever the client asked "
        "for. A call is then three parts: the wait for the first token, the generation after it, and what is left "
        "outside both. Reasoning tokens take time and are billed, and the reader never sees them."),
        "numbers": [
            _number("seconds_p50", "Median call", "seconds", "The middle call, start to finish, by nearest rank.",
                    at(50, "ms", everything), _count(calls, models)),
            _number("seconds_p90", "Slow call", "seconds", "The call 90% were faster than or equal to.", at(90, "ms", everything)),
            _number("seconds_p99", "Slowest calls", "seconds", "The call 99% were faster than or equal to.", at(99, "ms", everything)),
            _number("first_token_p50", "Median time to first token", "seconds",
                    "The middle call's time until the host sent its first token, a reasoning token included, as "
                    "OpenRouter recorded it.",
                    at(50, "first_token", split), {model: len(split(model)) for model in models}),
            _number("first_token_p90", "Slow time to first token", "seconds",
                    "The time to first token 90% of calls were faster than or equal to.", at(90, "first_token", split)),
            _number("in_one_piece", "Replies sent in one piece", "percent",
                    "Calls whose first token came in the last tenth of the generation: the host sent the whole reply "
                    "at once, so its time to first token is its time to the last.",
                    {model: _share(whole(call) for call in split(model)) for model in models}),
            _number("first_visible", "First visible token, estimated", "seconds",
                    "An estimate of when the reader would see something: the time to the first token, plus the "
                    "call's reasoning tokens at the rate it generated. The median across calls.",
                    {model: _scaled(_median(call.first_token + call.reasoning * (call.generating - call.first_token) / call.completion
                                            for call in split(model)), 1 / 1000) for model in models}),
            _number("outside", "Seconds outside the generation", "seconds",
                    "The median of the proxy's time for a call less the generation's: OpenRouter's routing, and the "
                    "network between this machine and it.",
                    {model: _scaled(_median(call.ms - call.generating for call in split(model)), 1 / 1000) for model in models}),
            _number("tokens_per_second", "Output tokens a second, whole call", "per_second",
                    "The median, across calls, of completion tokens over the call's seconds. The wait is in it, so "
                    "short answers look slower.",
                    {model: _median(call.completion / call.ms * 1000 for call in timed(model)) for model in models}),
            _number("generating_per_second", "Output tokens a second, generating", "per_second",
                    "The same once the first token has come: completion tokens over the generation's time after it, "
                    "for the calls not sent in one piece.",
                    {model: _median(call.completion / (call.generating - call.first_token) * 1000 for call in flowing(model)) for model in models},
                    {model: len(flowing(model)) for model in models}),
            _number("visible_per_second", "Visible tokens a second, whole call", "per_second",
                    "Over the whole call, the tokens the reader sees: completion tokens less reasoning tokens.",
                    {model: _median((call.completion - call.reasoning) / call.ms * 1000 for call in timed(model)) for model in models}),
            _number("reasoning_share", "Output that is reasoning", "percent",
                    "Reasoning tokens over completion tokens, across every call.",
                    {model: _ratio(sum(call.reasoning for call in _of(calls, model)), sum(call.completion for call in _of(calls, model)))
                     for model in models}),
            _number("retried", "Calls tried more than once", "count",
                    "Calls the proxy sent again after a 429, a 5xx or a dropped connection, and that were then answered.",
                    {model: sum(call.attempts > 1 for call in _of(calls, model)) for model in models}),
            _number("tried_more_hosts", "Calls that tried more than one host", "count",
                    "Calls for which OpenRouter went to a second host before one answered.",
                    {model: sum((call.tried or 0) > 1 for call in _of(calls, model)) for model in models}),
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
                   "its median call and its median time to first token.",
                   [_column("model", "Model"), _column("host", "Host"), _column("calls", "Calls", "count"),
                    _column("share", "Share", "percent"), _column("seconds", "Median call", "seconds"),
                    _column("first_token", "First token", "seconds")],
                   [{"model": model, "host": host, "calls": len(found := [call for call in _of(calls, model) if call.host == host]),
                     "share": _r(len(found) / len(_of(calls, model))), "seconds": _r(median(call.ms for call in found) / 1000),
                     "first_token": _r(_scaled(_median(call.first_token for call in found if call.first_token is not None), 1 / 1000))}
                    for model, host in hosts]),
        ]}


def stability(results: list[Result], models: list[str], listed: dict[str, Any] | None = None) -> dict[str, Any]:
    """listed: each model as OpenRouter listed it when the run was planned."""
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
            _number("temperature", "Default temperature", "count",
                    "The temperature OpenRouter lists as the model's default. The examples send no sampling settings, "
                    "so repeats are sampled at whatever the host defaults to.",
                    {model: ((listed or {}).get(model) or {}).get("temperature") for model in models}),
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


def before_after(calls: list[Call], results: list[Result], models: list[str]) -> dict[str, Any]:
    sent = {(call.model, call.task, call.repeat, call.variant): call for call in calls if call.variant}
    said = {(one.model, one.case, one.repeat, one.variant): one for one in results if one.variant}
    runs = sorted({key[:3] for key in (*sent, *said)})  # a model, a case and a repeat: asked once by each script
    both = lambda found, run: (found.get((*run, "before")), found.get((*run, "after")))
    words = lambda one: len(one.answer.split()) if one and one.answer else None
    # What changed from before.py to after.py: for each run with both, after over before, less one; then the median.
    change = lambda model, measure: _median(after / before - 1 for run in runs if run[0] == model
                                            for before, after in [measure(run)] if before and after is not None)
    of_calls = lambda field: lambda run: tuple(call and getattr(call, field) for call in both(sent, run))
    by_hand = {model: [one for one in _of(results, model) if one.variant == "before" and one.answer] for model in models}
    anyway = {model: [before for run in runs if run[0] == model for before, after in [both(sent, run)] if before and not after]
              for model in models}
    cases = sorted({(run[1], run[0]) for run in runs}, key=lambda pair: (pair[0], models.index(pair[1])))
    middle = lambda case, model, variant, measure: _r(_median(
        value for run in runs if (run[1], run[0]) == (case, model)
        if (value := measure((*run, variant))) is not None))
    prompt = lambda key: sent[key].prompt if key in sent else None
    seconds = lambda key: sent[key].ms / 1000 if key in sent else None
    cited = lambda key: len(said[key].cited) if key in said and said[key].answer else None
    return {"id": "before-after", "title": "Before and after", "lede": (
        "01 asks every question twice: before.py builds its request by hand, after.py builds it through CWA, and both "
        "go to the same model. So each pair is one model, one question and two requests, and what differs between its "
        "two answers is what the request changed. A chunk before.py sent and the assembler left out can only be cited "
        "from before.py's request."),
        "numbers": [
            _number("left_out_cited", "Left-out chunks cited, per answer", "count",
                    "The mean, across before.py's answers, of the chunks it cites that the committed assembly left "
                    "out, most often for scoring below the route's relevance threshold.",
                    {model: _mean(len(one.left_out) for one in by_hand[model]) for model in models},
                    {model: len(by_hand[model]) for model in models}),
            _number("answers_citing_left_out", "Answers citing a left-out chunk", "percent",
                    "Of before.py's answers, those that cite at least one chunk the assembly left out.",
                    {model: _share(bool(one.left_out) for one in by_hand[model]) for model in models}),
            _number("prompt_change", "Change in prompt tokens", "percent",
                    "For each run both scripts sent: after.py's prompt tokens over before.py's, less one; then the "
                    "median. after.py can send more: it keeps what the route protects and says where each part came from.",
                    {model: change(model, of_calls("prompt")) for model in models}),
            _number("cost_change", "Change in cost", "percent", "The same for what each call cost.",
                    {model: change(model, of_calls("cost")) for model in models}),
            _number("seconds_change", "Change in seconds", "percent", "The same for how long each call took.",
                    {model: change(model, of_calls("ms")) for model in models}),
            _number("words_change", "Change in the answer's words", "percent", "The same for the words in each answer.",
                    {model: change(model, lambda run: tuple(words(one) for one in both(said, run))) for model in models}),
            _number("asked_anyway", "Spent asking what after.py refused", "usd",
                    "What before.py's calls cost for the questions after.py's assembly refused, so sent to no model.",
                    {model: sum(call.cost for call in anyway[model]) if anyway[model] else None for model in models},
                    {model: len(anyway[model]) for model in models}),
        ],
        "tables": [
            _table("by_case", "Each question, before and after",
                   "For each question and model, the median across repeats of each script's prompt tokens, seconds, "
                   "words and citations, and the mean left-out chunks before.py's answer cites. Where after.py's "
                   "assembly refused, it has nothing to show.",
                   [_column("case", "Question"), _column("model", "Model"),
                    _column("prompt_before", "Prompt, before", "tokens"), _column("prompt_after", "after", "tokens"),
                    _column("seconds_before", "Seconds, before", "seconds"), _column("seconds_after", "after", "seconds"),
                    _column("words_before", "Words, before", "count"), _column("words_after", "after", "count"),
                    _column("cited_before", "Cited, before", "count"), _column("cited_after", "after", "count"),
                    _column("left_out", "Left out, cited", "count")],
                   [{"case": case, "model": model,
                     "prompt_before": middle(case, model, "before", prompt), "prompt_after": middle(case, model, "after", prompt),
                     "seconds_before": middle(case, model, "before", seconds), "seconds_after": middle(case, model, "after", seconds),
                     "words_before": middle(case, model, "before", lambda key: words(said.get(key))),
                     "words_after": middle(case, model, "after", lambda key: words(said.get(key))),
                     "cited_before": middle(case, model, "before", cited), "cited_after": middle(case, model, "after", cited),
                     "left_out": _r(_mean(len(one.left_out) for one in by_hand[model] if one.case == case))}
                    for case, model in cases]),
        ]}


def agents(results: list[Result], models: list[str]) -> dict[str, Any]:
    tasks = [one for one in results if one.case.split("/")[0] not in SAME_CONTEXT]
    named = lambda model, test: [passed for one in _of(tasks, model) for name, passed in one.checks if test(name)]
    failed = lambda test: ({model: named(model, test).count(False) if named(model, test) else None for model in models},
                           {model: len(named(model, test)) for model in models})
    grown = {model: [(one.estimates[-1] - one.estimates[0]) / (len(one.estimates) - 1)
                     for one in _of(tasks, model) if len(one.estimates) > 1] for model in models}
    walked = Counter((one.case, one.model, " → ".join(tool if approved else f"{tool} (refused)" for tool, approved in one.steps)
                      or "no tool call") for one in tasks)
    return {"id": "agents", "title": "Agents", "lede": (
        "04 and 05 are agents: the model chooses tool calls, a guard outside the model decides each one (R-5, R-15), "
        "and every inference is assembled from a snapshot of its own. So each model takes its own path, and these "
        "numbers are about the path: how long it was, what the guard refused, what the model did with text a tool "
        "result injected (R-10), and whether its answer says what it did."),
        "numbers": [
            _number("steps_median", "Tool calls per task", "count", "The median tool calls a task took, refused ones included.",
                    {model: _median(len(one.steps) for one in _of(tasks, model)) for model in models}, _count(tasks, models)),
            _number("steps_most", "Most tool calls in a task", "count", "The longest path any task took.",
                    {model: max((len(one.steps) for one in _of(tasks, model)), default=None) for model in models}),
            _number("tried", "Tool calls tried", "count", "Every tool call a model asked for, across its tasks.",
                    {model: sum(len(one.steps) for one in _of(tasks, model)) if _of(tasks, model) else None for model in models}),
            _number("refused_by_guard", "Refused by the guard", "count",
                    "Of those, the calls the guard refused: a tool not offered to the user's role, or arguments that "
                    "do not match its schema or the request's scope. A refused call never ran.",
                    {model: sum(not approved for one in _of(tasks, model) for _, approved in one.steps) if _of(tasks, model) else None
                     for model in models}),
            _number("injected_attempted", "Injected instruction: tried", "count",
                    "04's injected-instruction case: runs in which the model tried the call the injected text asked "
                    "for, whether or not the guard let it through.",
                    *failed(lambda name: name.startswith("untrusted never_attempts"))),
            _number("injected_recommended", "Injected instruction: recommended", "count",
                    "Runs in which the answer recommends to the user what the injected text asked for.",
                    *failed(lambda name: name.startswith("untrusted must_not_recommend"))),
            _number("injected_repeated", "Injected instruction: repeated", "count",
                    "Runs in which the answer says what the injected text scripted.",
                    *failed(lambda name: name == "untrusted mentions_none")),
            _number("claims_mismatch", "Answers that do not match the actions", "count",
                    "Runs in which the answer says a webhook was enabled or deleted when the run did not do it, or "
                    "does not say so when it did. A pattern check: the viewer shows each answer beside it.",
                    *failed(lambda name: name.endswith("claims_match_actions"))),
            _number("inferences_median", "Inferences per task", "count", "The median inferences that sent a request.",
                    {model: _median(len(one.estimates) for one in _of(tasks, model)) for model in models}),
            _number("growth_per_inference", "Tokens added per inference", "tokens",
                    "For each task of more than one inference: the assembler's count at the last less its count at "
                    "the first, over the inferences between; then the median. Each tool result is an item in the "
                    "next snapshot, and supersession keeps only the newest look at each thing (R-25).",
                    {model: _median(grown[model]) for model in models}, {model: len(grown[model]) for model in models}),
        ],
        "tables": [
            _table("paths", "The paths each model took",
                   "For each case and model, each sequence of tool calls it made, and in how many repeats.",
                   [_column("case", "Case"), _column("model", "Model"), _column("path", "Tool calls"), _column("repeats", "Repeats", "count")],
                   [{"case": case, "model": model, "path": path, "repeats": repeats}
                    for (case, model, path), repeats in sorted(walked.items(), key=lambda row: (row[0][0], models.index(row[0][1]), -row[1]))]),
        ]}


def verdicts(calls: list[Call], results: list[Result], models: list[str]) -> dict[str, Any]:
    graded = [one for one in results if one.clean is not None]
    counts = {model: (sum(passed for one in _of(graded, model) for _, passed in one.checks),
                      sum(len(one.checks) for one in _of(graded, model))) for model in models}
    answered = {model: Counter(call.host for call in _of(calls, model) if call.host) for model in models}
    # A check is one thing asked of one case: every model's every repeat of it either passed, or some did not.
    asked: dict[tuple[str, str | None, str], list[bool]] = defaultdict(list)
    named: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    for one in graded:
        for name, passed in one.checks:
            asked[one.case, one.variant, name].append(passed)
            named[name].append((one.model, passed))
    cells = _cells(graded)
    cases = sorted({key[1:] for key in cells}, key=str)
    every = lambda model, case: all(one.clean for one in cells[model, *case]) if (model, *case) in cells else None
    served: dict[str, set[str]] = defaultdict(set)
    for call in calls:
        served[call.job].add(call.host or "unnamed host")
    by_host: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for one in graded:
        if served[one.job]:
            by_host[one.model, next(iter(served[one.job])) if len(served[one.job]) == 1 else "several hosts"].append(one.clean)
    return {"id": "checks", "title": "Checks", "lede": (
        "The checks themselves. Each is a pattern over a run's record, so it is cheap and repeatable, and a handful of "
        "cases a few times over is a small sample: the range beside each pass rate says how small. When every model "
        "passes a check every time, that check tells no two models apart, so the page also says how many do."),
        "totals": [
            {"id": "failed", "label": "Checks failed", "unit": "count", "value": sum(graded - passed for passed, graded in counts.values()),
             "of": sum(graded for _, graded in counts.values()), "how": "Graded checks that failed, of all graded, across every model."},
            {"id": "always_passed", "label": "Checks every model always passed", "unit": "percent",
             "value": _r(_share(all(flags) for flags in asked.values())),
             "how": "Of the checks asked of each case, those every model passed in every repeat. They tell no two models apart."},
            {"id": "cases_with_failure", "label": "Cases with a failed check", "unit": "count",
             "value": sum(any(not one.clean for model in models for one in cells.get((model, *case), [])) for case in cases),
             "of": len(cases), "how": "Cases in which any model failed any check in any repeat, of the cases graded."},
        ],
        "numbers": [
            _number("checks_passed", "Checks passed", "percent",
                    "Graded checks passed over graded checks, 05's eval checks each counted. The range is where the "
                    "rate could lie over many more runs, 19 times in 20 (Wilson's interval). Two models whose ranges "
                    "overlap are not told apart by this run.",
                    {model: _ratio(*counts[model]) for model in models}, {model: counts[model][1] for model in models},
                    {model: wilson(*counts[model]) for model in models}),
            _number("hosts", "Hosts that answered", "count",
                    "OpenRouter may serve a model from several hosts, which need not run it the same way.",
                    {model: len(answered[model]) for model in models}),
            _number("busiest_host_share", "Calls answered by the busiest host", "percent",
                    "The share of a model's calls its most used host answered.",
                    {model: _ratio(max(answered[model].values(), default=0), sum(answered[model].values())) for model in models}),
        ],
        "tables": [
            _table("failures", "The checks that failed",
                   "Each check any model failed, across the cases that ask it: how often it failed, of how often it "
                   "was graded, and by which models.",
                   [_column("check", "Check"), _column("failed", "Failed", "count"), _column("graded", "Graded", "count"), _column("models", "Failed by")],
                   sorted(({"check": name, "failed": sum(not passed for _, passed in found), "graded": len(found),
                            "models": ", ".join(_short(model) for model in models if any(owner == model and not passed for owner, passed in found))}
                           for name, found in named.items() if not all(passed for _, passed in found)),
                          key=lambda row: (-row["failed"], row["check"]))),
            _table("disagreements", "Where one model passed and another did not",
                   "Each cell counts the cases the model in the row passed in every repeat and the model in the column "
                   "did not. Two models with zeros both ways were not told apart.",
                   [_column("model", "Passed every repeat"), *(_column(model, _short(model), "count") for model in models)],
                   [{"model": row, **{column: None if column == row else sum(every(row, case) is True and every(column, case) is False for case in cases)
                                      for column in models}} for row in models]),
            _table("by_host", "Results by the host that answered",
                   "A job's calls are usually answered by one host. For each: the results of the jobs it answered "
                   "alone, and the share of them with every check passed.",
                   [_column("model", "Model"), _column("host", "Host"), _column("results", "Results", "count"), _column("clean", "Every check passed", "percent")],
                   [{"model": model, "host": host, "results": len(flags), "clean": _r(_share(flags))}
                    for (model, host), flags in sorted(by_host.items(), key=lambda row: (models.index(row[0][0]), row[0][1]))]),
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


def _number(id: str, label: str, unit: str, how: str, values: dict[str, Any], n: dict[str, int] | None = None,
            ranges: dict[str, tuple[float, float] | None] | None = None) -> dict[str, Any]:
    """One value per model, with the formula behind it and, when it rests on a count of observations, that count and
    the range the value could have over many more."""
    return {"id": id, "label": label, "unit": unit, "how": how, "values": {model: _r(value) for model, value in values.items()},
            **({"n": n} if n is not None else {}),
            **({"ranges": {model: found and [_r(edge) for edge in found] for model, found in ranges.items()}} if ranges else {})}


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

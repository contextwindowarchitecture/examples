"""A run's numbers, for the viewer's "See the numbers" pages. Everything is read from the run's folder; nothing calls
a model.

    facts    one row per answered call, joined to the assembly whose payload it carried, one per result, and one per
             assembly: what it was offered, what it sent, and what it left out and why
    write    numbers.json, which grade.py writes beside summary.json: the run's models and its pages, each with what
             it says about CWA and a reading of the run (meaning.py), and the charts to draw of it (charts.py)
    pages    each a list of numbers, one value per model with the formula behind it, and tables that break them down:
             decisions   what the assembler did with what it was offered: sent, left out and why, summarized, refused
             tokens   what the same context costs in each model's own tokens, and the margin a route would need
             cost     what was charged against the list price, the factors it comes from, and what it bought
             speed    how long a call takes: the wait for its first token, the generation, and what is outside both
             stability   what repeats of the same case agree on: the checks, the answer's words, the tool calls
             before_after   01's two requests for the same question, by hand and through CWA, and what changed
             grounding   how far an answer stays within the request it answered: its words, and what it cites
             agents   what 04 and 05's agents tried, what the guard refused, and how their context grew
             verdicts   the checks themselves: how sure a pass rate is, and how far the checks tell the models apart

The checks say whether an answer passed. The numbers say what the same context cost each model in tokens, dollars and
seconds, how much its answers moved between repeats, and how far the checks tell the models apart.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations
from math import ceil, sqrt
from pathlib import Path
from statistics import mean, median
from typing import Any

import charts
import checks
import meaning
from config import ROOT, SAME_CONTEXT

# A word, for holding an answer to the request it answered: four letters or more, whatever its case. Short words are
# in every text; an id such as help:sign-in@6#0 gives help and sign-in, which the request holds when it sent the article.
WORD = re.compile(r"[a-z][a-z'-]{3,}")


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
    sent: tuple[str, ...]                 # the knowledge its last request carried, in the payload's order
    supported: float | None               # of the answer's words, the share found in the request it answered (WORD)
    budget: int | None                    # the route's budget.input
    recorded: tuple[str, ...] | None      # the tool calls of the example's committed recording of this scenario

    @property
    def clean(self) -> bool | None:
        """Every graded check passed. None when nothing was graded, as when the assembly refused."""
        return all(passed for _, passed in self.checks) if self.checks else None


@dataclass(frozen=True)
class Assembly:
    """One assembly, from its trace and its snapshot: what was sent, and what was left out and why."""
    job: str
    model: str
    case: str
    variant: str | None
    repeat: int
    name: str                                          # record, a route's name, or turn-<n>
    refused: str | None                                # the reason, when nothing was rendered
    estimate: int | None                               # trace.result.input_tokens
    budget: int
    margin: int | None
    sent: tuple[tuple[str, int], ...]                  # each item sent: its slot, and its tokens as the trace counts them
    left_out: tuple[tuple[str, str, int | None], ...]  # each item left out: the reason, the stage, and its size (below)
    summarized: tuple[tuple[int, int], ...]            # each item sent as a summary: its tokens whole, and as sent
    decided: tuple[str, ...]                           # what decided each conflict group, moot ones included
    threshold: float | None                            # the route's min_relevance for evidence.knowledge
    weakest_sent: float | None                         # the lowest relevance among the knowledge sent,
    strongest_left: float | None                       # and the highest among the knowledge that fell below the threshold


def facts(run: Path, summary: dict[str, Any]) -> tuple[list[Call], list[Result], list[Assembly]]:
    """summary: the run's summary.json (summary.py), which names every job and result."""
    lines: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if (run / "calls.jsonl").exists():
        for line in (run / "calls.jsonl").read_text(encoding="utf-8").splitlines():
            lines[json.loads(line)["job"]].append(json.loads(line))
    calls = [call for job in summary["jobs"] if job["exit"] is not None
             for call in _calls(run / job["job"], job, checks.last_attempt(lines[job["job"]]))]
    ended = [result for result in summary["results"] if result["exit"] == 0]
    return calls, [_result(run, result) for result in ended], [_assembly(run, result, folder) for result in ended
                                                                for folder in result["assemblies"]]


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
    carried = [assembly for assembly, trace in zip(result["assemblies"], traces) if trace["result"]]
    if result["request"]:
        context = json.dumps(_read(run / result["request"]), ensure_ascii=False)
    else:  # the payload its last inference rendered: system parts, tool definitions and the message
        context = json.dumps(_read(run / carried[-1] / "payload.json"), ensure_ascii=False) if carried else ""
    said, held = set(WORD.findall((answer or "").lower())), set(WORD.findall(context.lower()))
    recording = ROOT / result["case"].split("/")[0] / "scenarios" / result["case"].split("/", 1)[1] / "run.json"
    return Result(
        job=result["job"], model=result["model"], case=result["case"], variant=result["variant"], repeat=result["repeat"],
        checks=tuple((f"{check['measure']} {check['check']}", check["passed"]) for check in result["checks"]
                     if check["passed"] is not None and check["measure"] not in ("invariant", "run")),
        answer=answer, cited=cited, left_out=left_out,
        steps=tuple((step["tool"], step["approved"]) for step in answered.get("steps", [])),
        estimates=tuple(trace["result"]["input_tokens"] for trace in traces if trace["result"]),
        sent=tuple(row["item_id"] for row in traces[-1]["included"] if row["slot"] == "evidence.knowledge") if traces else (),
        supported=len(said & held) / len(said) if said and context else None,
        budget=traces[0]["budget"]["input"] if traces else None,
        recorded=tuple(step["tool"] for step in _read(recording).get("steps", [])) if recording.exists() else None)


def write(run: Path, summary: dict[str, Any]) -> dict[str, Any]:
    """The run's numbers.json, which the viewer's "See the numbers" pages read. summary: its summary.json."""
    calls, results, assemblies = facts(run, summary)
    models = list(summary["models"])
    pasted = frozenset(case["key"] for case in summary["cases"] if len(case["question"].strip().splitlines()) > 1)
    pages = [decisions(assemblies, models), tokens(calls, models, pasted, summary["models"]), cost(calls, results, summary), speed(calls, summary),
             stability(results, models, summary["models"]),
             grounding(results, models), before_after(calls, results, models), agents(results, models),
             verdicts(calls, results, models)]
    written = {"run": summary["run"], "graded": summary["graded"], "models": models, "pages": charts.add(meaning.explain(pages, models), results, models)}
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

PLANES = ("governance", "state", "evidence", "interaction")


def decisions(assemblies: list[Assembly], models: list[str]) -> dict[str, Any]:
    name = lambda made: made.case if made.name == "record" else f"{made.case} · {made.name}"
    # 01-03 send every model the same snapshots, so each of their requests is counted once, from whichever model's
    # record comes first. 04 and 05's snapshots follow each model's own tool calls, so those are counted by model.
    committed: dict[str, Assembly] = {}
    for made in assemblies:
        if made.case.split("/")[0] in SAME_CONTEXT:
            committed.setdefault(name(made), made)
    requests = [committed[request] for request in sorted(committed)]
    own = {model: [made for made in _of(assemblies, model) if made.case.split("/")[0] not in SAME_CONTEXT] for model in models}
    kept_out = lambda made: sum(size for _, _, size in made.left_out if size)
    saved = lambda made: sum(whole - shorter for whole, shorter in made.summarized)
    count = lambda model, reason: sum(left == reason for made in own[model] for left, _, _ in made.left_out) if own[model] else None
    reasons = {(reason, stage) for made in assemblies for reason, stage, _ in made.left_out}
    plane = lambda made, which: sum(size for slot, size in made.sent if slot.split(".")[0] == which)
    return {"id": "decisions", "title": "What CWA decided", "lede": (
        "What the assembler did with what it was offered, before any model was asked. Producers propose items; the "
        "assembler admits them, resolves conflicts, fits them to the route's budget, and renders what is left or "
        "refuses. Every decision is in a trace, and these numbers are counted from the traces. In 01–03 they are the "
        "same for every model: the context is decided before the model is known. In 04 and 05 each model's tool "
        "calls decide what its next snapshot holds."),
        "totals": [
            {"id": "refused", "label": "Requests refused", "unit": "count", "value": sum(bool(made.refused) for made in requests),
             "of": len(requests), "how": "Of 01–03's requests, each counted once: assemblies that rendered nothing, so no model was asked (R-17)."},
            {"id": "sent", "label": "Items sent", "unit": "count", "value": sum(len(made.sent) for made in requests),
             "of": sum(len(made.sent) + len(made.left_out) for made in requests),
             "how": "Items those requests carried, of the items their producers offered or reported."},
            {"id": "kept_out", "label": "Tokens kept out", "unit": "tokens", "value": sum(kept_out(made) for made in requests),
             "how": "The size of what those requests left out, by the route's own tokenizer, where the snapshot holds the text."},
            {"id": "summarized", "label": "Items sent as a summary", "unit": "count", "value": sum(len(made.summarized) for made in requests),
             "how": "Items a request carried as a summary written ahead of time, to fit the route's budget (R-18)."},
            {"id": "saved", "label": "Tokens those summaries saved", "unit": "tokens", "value": sum(saved(made) for made in requests),
             "how": "Those items' tokens whole, less their tokens as sent."},
        ],
        "numbers": [
            _number("assemblies", "Assemblies in 04 and 05", "count",
                    "The assemblies a model's agent runs made: one per inference, each from a snapshot of its own.",
                    {model: len(own[model]) or None for model in models}),
            _number("left_out_each", "Items left out per assembly", "count",
                    "The mean items an assembly left out, across a model's 04–05 assemblies.",
                    {model: _mean(len(made.left_out) for made in own[model]) for model in models}),
            _number("not_offered", "Tools not offered", "count",
                    "Capabilities the capability policy kept out of a snapshot because the user's role does not have "
                    "them: reason capability_not_allowed (R-15).",
                    {model: count(model, "capability_not_allowed") for model in models}),
            _number("superseded", "Looks replaced by a newer one", "count",
                    "Tool results left out because a newer result from the same source replaced them: reason "
                    "superseded (R-25). A model that never looks twice has none.",
                    {model: count(model, "superseded") for model in models}),
            _number("conflicts_decided", "Conflicts decided", "count",
                    "Conflict groups an assembly resolved by policy, authority or freshness, moot groups aside (R-11).",
                    {model: sum(by != "moot" for made in own[model] for by in made.decided) if own[model] else None for model in models}),
            _number("budget_peak", "Most of a budget used", "percent",
                    "The largest share of a route's budget.input an assembly's count reached, by the assembler's count.",
                    {model: max((made.estimate / made.budget for made in own[model] if made.estimate), default=None) for model in models}),
        ],
        "tables": [
            _table("requests", "Each request, and what became of what it was offered",
                   "01–03's requests, each once: whether it was sent or refused, the items offered and sent, the "
                   "assembler's count against the route's budget, the tokens kept out, and the tokens summaries saved.",
                   [_column("request", "Request"), _column("outcome", "Outcome"), _column("offered", "Offered", "count"),
                    _column("sent", "Sent", "count"), _column("estimate", "Count", "tokens"), _column("budget", "Budget", "tokens"),
                    _column("used", "Used", "percent"), _column("kept_out", "Kept out", "tokens"), _column("saved", "Saved", "tokens")],
                   [{"request": name(made), "outcome": f"refused: {made.refused}" if made.refused else "sent",
                     "offered": len(made.sent) + len(made.left_out), "sent": len(made.sent), "estimate": made.estimate,
                     "budget": made.budget, "used": _r(_ratio(made.estimate or 0, made.budget)) if made.estimate else None,
                     "kept_out": kept_out(made), "saved": saved(made)} for made in requests]),
            _table("planes", "What each request spent its budget on",
                   "The tokens of the items sent, by plane, as the trace counts them; and what is around them: the "
                   "wrappers and separators the renderer adds, which count against the budget too (R-16).",
                   [_column("request", "Request"), *(_column(which, which.capitalize(), "tokens") for which in PLANES),
                    _column("around", "Around the items", "tokens")],
                   [{"request": name(made), **{which: plane(made, which) for which in PLANES},
                     "around": made.estimate - sum(size for _, size in made.sent)} for made in requests if made.estimate]),
            _table("reasons", "Why items were left out",
                   "Each reason, with the stage that gave it: a producer reporting what it suppressed, or the "
                   "assembler. For 01–03, the items and their tokens, each request once.",
                   [_column("reason", "Reason"), _column("stage", "Stage"), _column("committed", "01–03, items", "count"),
                    _column("tokens", "01–03, tokens", "tokens")],
                   [{"reason": reason, "stage": stage,
                     "committed": sum((left, by) == (reason, stage) for made in requests for left, by, _ in made.left_out),
                     "tokens": sum(size or 0 for made in requests for left, by, size in made.left_out if (left, by) == (reason, stage))}
                    for reason, stage in sorted(reasons)]),
            _table("reasons_by_model", "Why each model's items were left out, in 04 and 05",
                   "Each reason, with the stage that gave it: the items left out across each model's own assemblies, "
                   "since in 04 and 05 the model's tool calls decide what each snapshot holds.",
                   [_column("reason", "Reason, by stage"), *(_column(model, _short(model), "count") for model in models)],
                   [{"reason": f"{reason} · {stage}",
                     **{model: sum((left, by) == (reason, stage) for made in own[model] for left, by, _ in made.left_out) for model in models}}
                    for reason, stage in sorted(reasons)]),
            _table("relevance", "How close each relevance call was",
                   "For each request whose route sets a threshold for knowledge: the threshold, the lowest score sent "
                   "and the highest score left out (R-13).",
                   [_column("request", "Request"), _column("threshold", "Threshold", "count"), _column("weakest_sent", "Lowest sent", "count"),
                    _column("strongest_left", "Highest left out", "count")],
                   [{"request": name(made), "threshold": made.threshold, "weakest_sent": made.weakest_sent, "strongest_left": made.strongest_left}
                    for made in requests if made.threshold is not None and (made.weakest_sent is not None or made.strongest_left is not None)]),
        ],
        # A card per model for what 04 and 05's assemblies did, the fullest budget first. 01–03's requests are the same
        # for every model, so their tables stay on the page.
        "cards": {"order": "budget_peak", "down": True, "head": ["assemblies", "left_out_each", "superseded", "budget_peak"],
                  "groups": [{"title": "What it assembled", "numbers": ["assemblies", "left_out_each", "budget_peak"]},
                             {"title": "What it decided", "numbers": ["not_offered", "superseded", "conflicts_decided"]}],
                  "tables": ["reasons_by_model"]}}


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
            _table("requests", "Each request, as the assembler counted it",
                   "Each 01–03 request: the assembler's estimate, OpenRouter's count of the same request with its own "
                   "tokenizer, the route's budget.input and how much of it the estimate uses.",
                   [_column("case", "Request"), _column("question", "Question"), _column("estimate", "Estimate", "tokens"),
                    _column("normalized", "OpenRouter's count", "tokens"), _column("budget", "Budget", "tokens"), _column("used", "Used", "percent")],
                   [{"case": case, "question": "pastes a block" if task[case] in pasted else "one line",
                     "estimate": call.estimate, "normalized": _median(one.normalized for one in same if _case(one) == case and one.normalized),
                     "budget": call.budget, "used": _r(call.estimate / call.budget)} for case, call in first.items()]),
            _table("counts_by_case", "The same request, counted by each model",
                   "Each 01–03 request: the tokens each model's host counted, the median across repeats.",
                   [_column("case", "Request"), *(_column(model, _short(model), "tokens") for model in models)],
                   [{"case": case, **{model: requests[model].get(case, (None, None))[1] for model in models}} for case in first]),
            _table("margin_by_case", "The margin each request needed",
                   "Each 01–03 request: the margin its route declares, then for each model the host's count over the "
                   "estimate, less one. A request is covered when that is within the declared margin.",
                   [_column("case", "Request"), _column("declared", "Declared", "percent"),
                    *(_column(model, _short(model), "percent") for model in models)],
                   [{"case": case, "declared": (call.margin or 0) / 100,
                     **{model: _r(requests[model][case][1] / call.estimate - 1) if case in requests[model] else None
                        for model in models}} for case, call in first.items()]),
        ],
        # A card per model, in the order of the margin it needed, as the chart of margins sets them. The table of
        # requests stays on the page; each card takes its model's counts and margins.
        "cards": {"order": "margin_needed", "head": ["margin_needed", "margin_covered", "tokens_per_estimated", "tokens_added"],
                  "groups": [{"title": "How the host counts", "numbers": ["tokenizer", "tokens_per_estimated", "tokens_added", "tokens_per_estimated_pasted"]},
                             {"title": "The margin", "numbers": ["margin_needed", "margin_covered", "over_budget"]},
                             {"title": "The window", "numbers": ["context", "budget_share", "cached_share", "resend_factor"]}],
                  "tables": ["counts_by_case", "margin_by_case"],
                  # Both are about the same requests in the same order, so a card sets them out as one list.
                  "merge": [{"title": "Each request", "columns": {"counts_by_case": "The host's count", "margin_by_case": "Margin needed"}}]}}


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
        "included, at the output price. Every factor is in each model's card below, so a gap between two models can "
        "be read as the factors that differ."),
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
        ],
        # A card per model, the largest spend first, as the chart of spend sets them: each holds its row of where the
        # charge comes from and its cost by example, which nobody reads across fourteen models.
        "cards": {"order": "spend", "down": True, "head": ["spend", "cost_per_clean_result", "charged_over_list", "prompt_share_of_spend"],
                  "groups": [{"title": "What was spent", "numbers": ["spend", "planned", "spent_over_planned", "charged_over_list", "prompt_share_of_spend"]},
                             {"title": "What it bought", "numbers": ["cost_per_passed_check", "cost_per_clean_result"]}],
                  "tables": ["identity", "by_example"]}}


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
        ],
        # A card per model, in the order the chart draws them: closed on what most readers compare, open on every
        # number by the question it answers, and on the model's own rows of the tables, which nobody reads across models.
        "cards": {"order": "seconds_p50", "head": ["seconds_p50", "first_token_p50", "tokens_per_second", "reasoning_share"],
                  "groups": [{"title": "The wait", "numbers": ["first_token_p50", "first_token_p90", "first_visible", "seconds_p50", "seconds_p90", "seconds_p99"]},
                             {"title": "The writing", "numbers": ["tokens_per_second", "generating_per_second", "visible_per_second", "reasoning_share"]},
                             {"title": "Around the call", "numbers": ["outside", "in_one_piece", "retried", "tried_more_hosts", "cut_short"]}],
                  "tables": ["seconds_by_example", "by_host"]}}


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
        ],
        # A card per model, the steadiest first as the chart of passing sets them, each with its own cases that
        # passed only sometimes or never.
        "cards": {"order": "pass_every", "down": True, "head": ["pass_every", "pass_average", "answer_similarity", "same_tool_path"],
                  "groups": [{"title": "Passing", "numbers": ["pass_average", "pass_every", "cases_some", "cases_none"]},
                             {"title": "Sameness", "numbers": ["temperature", "answer_similarity", "same_citations", "same_tool_path"]}],
                  "tables": ["not_every_repeat"]}}


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
        ],
        # A card per model, the answers citing what the threshold left out first, each with its own questions.
        "cards": {"order": "answers_citing_left_out", "down": True, "head": ["answers_citing_left_out", "prompt_change", "cost_change", "seconds_change"],
                  "groups": [{"title": "What the threshold kept out", "numbers": ["left_out_cited", "answers_citing_left_out", "asked_anyway"]},
                             {"title": "What changed", "numbers": ["prompt_change", "cost_change", "seconds_change", "words_change"]}],
                  "tables": ["by_case"]}}


def grounding(results: list[Result], models: list[str]) -> dict[str, Any]:
    through = {model: [one for one in _of(results, model) if one.answer and one.variant != "before"] for model in models}
    by_hand = {model: [one for one in _of(results, model) if one.answer and one.variant == "before"] for model in models}
    carried = {model: [one for one in through[model] if one.sent] for model in models}  # answers whose request carried knowledge
    named = lambda one: [citation for citation in one.cited if citation in one.sent]
    ranks = lambda model: [one.sent.index(citation) + 1 for one in carried[model] for citation in named(one)]
    cases = sorted({(one.case, model) for model in models for one in carried[model]}, key=lambda pair: (pair[0], models.index(pair[1])))
    here = lambda case, model: [one for one in carried[model] if one.case == case]
    return {"id": "grounding", "title": "Grounding", "lede": (
        "How far an answer stays within the request it answered. CWA decides what a model is sent, and marks each "
        "article with the id an answer can cite. These numbers hold each answer to its own request: the words it "
        "uses that the request held, and the articles it cites of those the request carried. They are counts of "
        "words and ids, not a judgement of whether the answer is right."),
        "numbers": [
            _number("words_in_context", "Answer's words found in its request", "percent",
                    "For each answer to a request built through CWA: of its distinct words of four letters or more, "
                    "the share the request also holds. The mean across answers.",
                    {model: _mean(one.supported for one in through[model] if one.supported is not None) for model in models},
                    {model: sum(one.supported is not None for one in through[model]) for model in models}),
            _number("words_in_context_before", "The same, for before.py's requests", "percent",
                    "The same for 01's answers to the request before.py built by hand, which carries every chunk "
                    "retrieval returned.",
                    {model: _mean(one.supported for one in by_hand[model] if one.supported is not None) for model in models}),
            _number("cited_of_sent", "Articles cited, of those sent", "percent",
                    "Across the answers whose request carried knowledge: the articles they cite that it carried, over "
                    "the articles it carried.",
                    {model: _ratio(sum(len(named(one)) for one in carried[model]), sum(len(one.sent) for one in carried[model])) for model in models},
                    {model: len(carried[model]) for model in models}),
            _number("citations_sent", "Citations that name what was sent", "percent",
                    "Of those answers' citations, the ones naming an article the request carried. The rest name "
                    "something the model was never sent.",
                    {model: _ratio(sum(len(named(one)) for one in carried[model]), sum(len(one.cited) for one in carried[model])) for model in models}),
            _number("uncited", "Answers that cite nothing", "percent",
                    "Of those answers, the ones with no citation at all.",
                    {model: _share(not one.cited for one in carried[model]) for model in models}),
            _number("cited_rank", "Where the cited articles sat", "count",
                    "The median place, in the request's order, of the articles an answer cites: 1 is the first, which "
                    "the route's order makes the most relevant.",
                    {model: _median(ranks(model)) for model in models}, {model: len(ranks(model)) for model in models}),
            _number("cites_first", "Answers that cite the first article", "percent",
                    "Of the answers that cite an article they were sent, those citing the first one in the request.",
                    {model: _share(one.sent[0] in one.cited for one in carried[model] if named(one)) for model in models}),
        ],
        "tables": [
            _table("by_case", "Each case, by model",
                   "For each case whose request carried knowledge: the articles sent, the median citations in an "
                   "answer, and the mean share of an answer's words found in its request.",
                   [_column("case", "Case"), _column("model", "Model"), _column("sent", "Articles sent", "count"),
                    _column("cited", "Citations", "count"), _column("supported", "Words in the request", "percent")],
                   [{"case": case, "model": model, "sent": _median(len(one.sent) for one in here(case, model)),
                     "cited": _median(len(one.cited) for one in here(case, model)),
                     "supported": _r(_mean(one.supported for one in here(case, model) if one.supported is not None))}
                    for case, model in cases]),
        ],
        # A card per model, the most of what it was sent cited first as the chart sets them, each with its own cases.
        "cards": {"order": "cited_of_sent", "down": True, "head": ["cited_of_sent", "citations_sent", "uncited", "words_in_context"],
                  "groups": [{"title": "What it cited", "numbers": ["cited_of_sent", "citations_sent", "uncited", "cited_rank", "cites_first"]},
                             {"title": "Where its words came from", "numbers": ["words_in_context", "words_in_context_before"]}],
                  "tables": ["by_case"]}}


def agents(results: list[Result], models: list[str]) -> dict[str, Any]:
    tasks = [one for one in results if one.case.split("/")[0] not in SAME_CONTEXT]
    named = lambda model, test: [passed for one in _of(tasks, model) for name, passed in one.checks if test(name)]
    failed = lambda test: ({model: named(model, test).count(False) if named(model, test) else None for model in models},
                           {model: len(named(model, test)) for model in models})
    grown = {model: [(one.estimates[-1] - one.estimates[0]) / (len(one.estimates) - 1)
                     for one in _of(tasks, model) if len(one.estimates) > 1] for model in models}
    followed = {model: [one for one in _of(tasks, model) if one.recorded] for model in models}
    binds = {model: [(one.budget - one.estimates[0]) / growth for one in _of(tasks, model) if one.budget and len(one.estimates) > 1
                     and (growth := (one.estimates[-1] - one.estimates[0]) / (len(one.estimates) - 1)) > 0] for model in models}
    longest = max((len(one.estimates) for one in tasks), default=0)
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
            _number("recorded_path", "Runs that took the recorded path", "percent",
                    "04 commits a recording of each scenario. Of a model's runs of those, the ones that made the same "
                    "tool calls in the same order.",
                    {model: _share(tuple(tool for tool, _ in one.steps) == one.recorded for one in followed[model]) for model in models},
                    {model: len(followed[model]) for model in models}),
            _number("steps_over_recorded", "Tool calls, over the recording's", "ratio",
                    "The median, across those runs, of the tool calls a run made over the recording's.",
                    {model: _median(len(one.steps) / len(one.recorded) for one in followed[model]) for model in models}),
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
            _number("inferences_until_budget", "Inferences until the budget binds", "count",
                    "For each such task: the room left in the route's budget.input after its first inference, over "
                    "the tokens it added per inference; then the median. Past that, fitting starts to shed and "
                    "summarize (R-16).",
                    {model: _median(binds[model]) for model in models}, {model: len(binds[model]) for model in models}),
        ],
        "tables": [
            _table("paths", "The paths each model took",
                   "For each case and model, each sequence of tool calls it made, and in how many repeats.",
                   [_column("case", "Case"), _column("model", "Model"), _column("path", "Tool calls"), _column("repeats", "Repeats", "count")],
                   [{"case": case, "model": model, "path": path, "repeats": repeats}
                    for (case, model, path), repeats in sorted(walked.items(), key=lambda row: (row[0][0], models.index(row[0][1]), -row[1]))]),
            _table("growth", "The assembler's count at each inference",
                   "For each model, the assembler's count at each inference of a 04 or 05 task: the median across the "
                   "tasks that reached that inference.",
                   [_column("model", "Model"), *(_column(str(n), f"Inference {n}", "tokens") for n in range(1, longest + 1))],
                   [{"model": model, **{str(n): _median(one.estimates[n - 1] for one in _of(tasks, model) if len(one.estimates) >= n)
                                        for n in range(1, longest + 1)}} for model in models if any(one.estimates for one in _of(tasks, model))]),
        ],
        # A card per model, the most runs on the recorded path first, each with its own paths and its count at each
        # inference: thirteen numbers are too many columns for a table that fits a page.
        "cards": {"order": "recorded_path", "down": True, "head": ["steps_median", "recorded_path", "refused_by_guard", "claims_mismatch"],
                  "groups": [{"title": "The path", "numbers": ["steps_median", "steps_most", "recorded_path", "steps_over_recorded", "inferences_median"]},
                             {"title": "The guard", "numbers": ["tried", "refused_by_guard", "injected_attempted", "injected_recommended", "injected_repeated", "claims_mismatch"]},
                             {"title": "The budget", "numbers": ["growth_per_inference", "inferences_until_budget"]}],
                  "tables": ["paths", "growth"]}}


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
    # The cases one model passed in every repeat and another did not.
    beat = lambda model, other: sum(every(model, case) is True and every(other, case) is False for case in cases)
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
            _table("versus", "Against each other model",
                   "For each pair of models, both ways: the cases the model passed in every repeat and the other did "
                   "not, and the cases the other passed in every repeat and the model did not. Two models with zeros "
                   "both ways were not told apart.",
                   [_column("model", "Model"), _column("other", "Against"), _column("won", "Passed, the other did not", "count"),
                    _column("lost", "The other passed, it did not", "count")],
                   [{"model": model, "other": _short(other), "won": beat(model, other), "lost": beat(other, model)}
                    for model in models for other in models if other != model]),
            _table("by_host", "Results by the host that answered",
                   "A job's calls are usually answered by one host. For each: the results of the jobs it answered "
                   "alone, and the share of them with every check passed.",
                   [_column("model", "Model"), _column("host", "Host"), _column("results", "Results", "count"), _column("clean", "Every check passed", "percent")],
                   [{"model": model, "host": host, "results": len(flags), "clean": _r(_share(flags))}
                    for (model, host), flags in sorted(by_host.items(), key=lambda row: (models.index(row[0][0]), row[0][1]))]),
        ],
        # A card per model, the most checks passed first as the chart sets them, each with how it fared against each
        # other model and its results by host.
        "cards": {"order": "checks_passed", "down": True, "head": ["checks_passed", "hosts", "busiest_host_share"],
                  "groups": [{"title": "The checks", "numbers": ["checks_passed"]}, {"title": "The hosts", "numbers": ["hosts", "busiest_host_share"]}],
                  "tables": ["versus", "by_host"]}}


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


def _assembly(run: Path, result: dict[str, Any], folder: str) -> Assembly:
    trace, snapshot = _read(run / folder / "trace.json"), _read(run / folder / "snapshot.json")
    items = {item["id"]: item for batch in snapshot["batches"] for item in batch["items"]}
    # A trace counts what was sent, not what was left out. The snapshot holds a left-out item's text unless its
    # producer reported it by id alone, and estimate-utf8/v1 is the bytes of a text over 4, rounded up: its body's
    # size by the route's own tokenizer, without the wrapper it would have been rendered in.
    sized = snapshot.get("tokenizer") == "estimate-utf8/v1"
    size = lambda id: (len(items[id]["body"].encode("utf-8")) + 3) // 4 if sized and id in items else None
    knowledge = [row["item_id"] for row in trace["included"] if row["slot"] == "evidence.knowledge"]
    below = [row["item_id"] for row in trace["excluded"] if row["reason"] == "below_threshold" and row["item_id"] in items]
    relevance = lambda ids: [items[id]["relevance"] for id in ids if id in items and items[id].get("relevance") is not None]
    return Assembly(
        job=result["job"], model=result["model"], case=result["case"], variant=result["variant"], repeat=result["repeat"],
        name=Path(folder).name, refused=trace["refused"]["reason"] if trace["refused"]["bool"] else None,
        estimate=trace["result"]["input_tokens"] if trace["result"] else None, budget=trace["budget"]["input"],
        margin=trace["budget"].get("margin_percent"),
        sent=tuple((row["slot"], row["tokens"]) for row in trace["included"]),
        left_out=tuple((row["reason"], row["stage"], size(row["item_id"])) for row in trace["excluded"]),
        summarized=tuple((row["from"], row["to"]) for row in trace["compressed"]),
        decided=tuple(group["decided_by"] for group in trace["conflicts"]),
        threshold=(snapshot["route_policy"]["slots"].get("evidence.knowledge") or {}).get("min_relevance"),
        weakest_sent=min(relevance(knowledge), default=None), strongest_left=max(relevance(below), default=None))


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

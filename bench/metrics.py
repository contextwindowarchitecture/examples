"""A run's numbers, for the viewer's "See the numbers" pages. Everything is read from the run's folder; nothing calls
a model.

    facts    one row per answered call, joined to the assembly whose payload it carried, and one per result

The checks say whether an answer passed. The numbers say what the same context cost each model in tokens, dollars and
seconds, how much its answers moved between repeats, and how far the checks tell the models apart.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import checks
from config import ROOT


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
             for call in _calls(run / job["job"], job, _last_attempt(lines[job["job"]]))]
    return calls, [_result(run, result) for result in summary["results"] if result["exit"] == 0]


def _last_attempt(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A resumed job numbers its calls from 1 again, and what its failed attempt sent stays in calls.jsonl."""
    starts = [n for n, line in enumerate(lines) if line["call"] == 1]
    return lines[starts[-1]:] if starts else lines


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


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

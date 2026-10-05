"""A run's numbers: the facts read from its files, on runs built from the committed scenarios, then the arithmetic and
each page's numbers on facts written out by hand."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import checks
import metrics
import summary
from config import ROOT
from test_checks import write

MODEL = "vendor/model"
ANSWER = ROOT / "01-docs-qa" / "scenarios" / "01-answer"
OWNER = ROOT / "04-tools" / "scenarios" / "01-owner-reenables"


def job(run: Path, example: str, case: str, answered: dict[str, Any], scenario: Path | None = None, repeat: int = 1) -> str:
    """A job that ran to the end: its record, copied from a committed scenario when one is given, and its answer."""
    name = f"vendor-model/{example}/{case}/{repeat}"
    if scenario:
        shutil.copytree(scenario, run / name / "record")
    write(run / name / "record" / "run.json", answered)
    write(run / name / "job.json", {"model": MODEL, "example": example, "case": case, "repeat": repeat, "exit": 0, "seconds": 4.2})
    return name


def logged(run: Path, name: str, call: int, prompt: int, **more: Any) -> None:
    """A line of calls.jsonl, as the proxy writes one."""
    line = {"job": name, "call": call, "status": 200, "error": None, "model": MODEL, "answered_by": MODEL, "host": "SomeHost",
            "tokens": {"prompt": prompt, "completion": 200, "reasoning": 50, "cached": 0}, "cost": 0.004, "ms": 1500,
            "attempts": [{"status": 200, "ms": 1500}]} | more
    with (run / "calls.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(line) + "\n")


def called(run: Path, name: str, *prompts: int) -> None:
    """What the proxy keeps of a job's calls, one per prompt size: the log line and the response."""
    for call, prompt in enumerate(prompts, start=1):
        logged(run, name, call, prompt)
        write(run / name / "calls" / f"{call}.response.json", {"choices": [{"finish_reason": "stop"}], "usage": {
            "cost_details": {"upstream_inference_prompt_cost": 0.001, "upstream_inference_completions_cost": 0.003}}})


def graded(run: Path, names: list[str], found: dict[str, list[checks.Check]] | None = None) -> dict[str, Any]:
    """The run's manifest and its summary, which the facts are read with."""
    write(run / "manifest.json", {
        "run": run.name, "started": "2026-10-02T15:30:07Z", "repository": {"commit": "abc1234", "dirty": False},
        "assembler": [{"example": "01-docs-qa", "tag": "draft-release", "commit": "49b321e"}],
        "models": {MODEL: {"label": "vendor-model", "input_price": 2e-06, "output_price": 1e-05, "tools": True, "free": False}},
        "skipped": [], "jobs": names})
    (run / "bench.toml").write_text('models = ["vendor/model"]\n\n[run]\nmax_cost_usd = 1.5\n')
    return summary.write(run, found or {})


def test_a_call_is_joined_to_the_assembly_whose_payload_it_carried(tmp_path: Path) -> None:
    name = job(tmp_path, "01-docs-qa", "01-answer/after", {"answer": "Check spam [help:sign-in@6#0].", "error": None}, ANSWER)
    called(tmp_path, name, 375)
    found = {name: [checks.Check("invariant", "payload_sent", True, ""), checks.Check("answer", "answered", True, ""),
                    checks.Check("answer", "mentions_any", False, ""), checks.Check("grounding", "cites_of_the_articles_sent", None, "1 of 2")]}
    [call], [result] = metrics.facts(tmp_path, graded(tmp_path, [name], found))
    trace = json.loads((ANSWER / "trace.json").read_text())
    assert (call.estimate, call.budget, call.margin) == (trace["result"]["input_tokens"], 1500, 15)
    assert (call.task, call.variant, call.repeat, call.assembly) == ("01-docs-qa/01-answer", "after", 1, "record")
    assert (call.prompt, call.completion, call.reasoning, call.finish, call.prompt_cost) == (375, 200, 50, "stop", 0.001)
    # A result's checks are the graded ones about the model: not the invariants, nor what is only reported.
    assert result.checks == (("answer answered", True), ("answer mentions_any", False)) and result.clean is False
    assert (result.case, result.variant, result.cited, result.estimates) == ("01-docs-qa/01-answer", "after", ("help:sign-in@6#0",), (283,))


def test_before_py_assembles_nothing_so_its_call_has_no_estimate(tmp_path: Path) -> None:
    left_out = json.loads((ANSWER / "trace.json").read_text())["excluded"][0]["item_id"]
    name = job(tmp_path, "01-docs-qa", "01-answer/before", {"answer": f"Check spam [help:sign-in@6#0] [{left_out}].", "error": None})
    write(tmp_path / name / "record" / "request.json", {"messages": [{"role": "user", "content": "..."}]})
    called(tmp_path, name, 560)
    [call], [result] = metrics.facts(tmp_path, graded(tmp_path, [name]))
    assert (call.prompt, call.estimate, call.budget, call.assembly) == (560, None, None, None)
    # What it cited that the committed assembly left out: only its own request could have carried it.
    assert result.left_out == (left_out,) and result.clean is None


def test_a_refused_assembly_has_a_result_and_no_call(tmp_path: Path) -> None:
    name = job(tmp_path, "01-docs-qa", "03-off-topic/after", {"answer": None, "refused": "evidence_required"},
               ROOT / "01-docs-qa" / "scenarios" / "03-off-topic")
    calls, [result] = metrics.facts(tmp_path, graded(tmp_path, [name, "vendor-model/02-account-aware/01-team-plan/1"]))
    # The second job never ran: it has no folder, and no rows.
    assert calls == [] and (result.answer, result.estimates, result.cited) == (None, (), ())


def test_a_resumed_job_counts_only_its_last_attempt(tmp_path: Path) -> None:
    name = "vendor-model/01-docs-qa/01-answer/after/1"
    logged(tmp_path, name, 1, 111)  # the attempt that failed: run.py emptied its folder, and the line stays
    job(tmp_path, "01-docs-qa", "01-answer/after", {"answer": "Check spam.", "error": None}, ANSWER)
    called(tmp_path, name, 375)
    [call], _ = metrics.facts(tmp_path, graded(tmp_path, [name]))
    assert (call.prompt, call.estimate) == (375, 283)


def test_an_agents_calls_follow_its_inferences_and_its_result_holds_its_tool_calls(tmp_path: Path) -> None:
    ran = json.loads((OWNER / "run.json").read_text())
    name = job(tmp_path, "04-tools", "01-owner-reenables", ran, OWNER)
    called(tmp_path, name, 1200, 1300, 1400, 1500, 1600)
    calls, [result] = metrics.facts(tmp_path, graded(tmp_path, [name]))
    assert [call.assembly for call in calls] == ["turn-1", "turn-2", "turn-3", "turn-4", "turn-5"]
    assert [call.estimate for call in calls] == list(result.estimates) and len(set(result.estimates)) > 1
    assert result.steps == tuple((step["tool"], step["approved"]) for step in ran["steps"])


def test_05s_calls_belong_to_the_eval_case_that_made_them(tmp_path: Path) -> None:
    first, second = [case["id"] for case in json.loads((ROOT / "05-production" / "evals" / "cases.json").read_text())["cases"]][:2]
    name = job(tmp_path, "05-production", "evals", {})
    for case, turn in ((second, "turn-2"), (first, "turn-1")):  # written out of order: the suite's order decides
        shutil.copytree(OWNER / turn, tmp_path / name / "record" / case / "turn-1")
    called(tmp_path, name, 1200, 1300)
    calls, _ = metrics.facts(tmp_path, graded(tmp_path, [name]))
    assert [call.task for call in calls] == [f"05-production/{first}", f"05-production/{second}"]
    assert calls[0].estimate == json.loads((OWNER / "turn-1" / "trace.json").read_text())["result"]["input_tokens"]

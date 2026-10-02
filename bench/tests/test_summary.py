"""The summary the viewer reads: which constructs each result exercised, read from its own traces, and the totals by
model; and the index of runs."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import checks
import constructs
import summary
from config import ROOT


def exercised(record: Path, steps: int = 0) -> list[str]:
    return constructs.exercised(summary.facts(record, "x", steps))


def test_each_committed_scenario_exercises_the_constructs_its_trace_shows() -> None:
    scenarios = ROOT / "02-account-aware" / "scenarios"
    assert "conflicts" in exercised(scenarios / "02-memory-disagrees")
    assert {"scope", "relevance-threshold"} <= set(exercised(scenarios / "03-memory-leak"))
    assert "producer-exclusions" in exercised(scenarios / "01-team-plan")
    assert "budget-and-fitting" in exercised(ROOT / "03-budget-and-routes" / "scenarios" / "02-small-route")
    off_topic = exercised(ROOT / "01-docs-qa" / "scenarios" / "03-off-topic")
    assert "evidence-required" in off_topic and "placement-and-rendering" not in off_topic


def test_an_escalation_is_a_refused_route_then_one_that_sent(tmp_path: Path) -> None:
    record = tmp_path / "record"
    shutil.copytree(ROOT / "03-budget-and-routes" / "scenarios" / "03-pasted-log", record / "account-help-small")
    shutil.copytree(ROOT / "03-budget-and-routes" / "scenarios" / "04-pasted-log-escalated", record / "account-help")
    assert "escalation" in exercised(record)
    assert "escalation" not in exercised(ROOT / "03-budget-and-routes" / "scenarios" / "03-pasted-log")


def test_an_agent_run_exercises_what_its_own_path_did() -> None:
    owner = ROOT / "04-tools" / "scenarios" / "01-owner-reenables"
    found = exercised(owner, steps=4)
    assert {"capabilities-and-guard", "supersession", "untrusted-content"} <= set(found)


def test_every_construct_names_its_requirements_and_measures() -> None:
    for construct in constructs.CONSTRUCTS:
        assert construct.spec and construct.description and construct.title
        assert set(construct.measures) <= set(checks_measures())


def checks_measures() -> set[str]:
    return {"invariant", "answer", "grounding", "conflict", "excluded", "untrusted", "actions", "refusal", "claims",
            "guard", "evals"}


def run_with(tmp_path: Path) -> Path:
    """A run of one model: 01's 01-answer through after.py, graded, and 02's 01-team-plan, which never ran."""
    run = tmp_path / "results" / "2026-10-02T153007Z-abc1234"
    job = run / "vendor-model" / "01-docs-qa" / "01-answer" / "after" / "1"
    shutil.copytree(ROOT / "01-docs-qa" / "scenarios" / "01-answer", job / "record")
    (job / "record" / "run.json").write_text(json.dumps({"provider": "openai", "model": "vendor/model",
                                                          "answer": "Check your inbox.", "error": None}))
    (job / "job.json").write_text(json.dumps({"model": "vendor/model", "example": "01-docs-qa", "case": "01-answer/after",
                                              "repeat": 1, "exit": 0, "seconds": 4.2}))
    (run / "manifest.json").write_text(json.dumps({
        "run": run.name, "started": "2026-10-02T15:30:07Z", "repository": {"commit": "abc1234", "dirty": False},
        "assembler": [{"example": "01-docs-qa", "tag": "draft-release", "commit": "49b321e"}],
        "models": {"vendor/model": {"label": "vendor-model", "input_price": 2e-06, "output_price": 1e-05, "tools": True,
                                    "free": False}},
        "skipped": [], "jobs": ["vendor-model/01-docs-qa/01-answer/after/1", "vendor-model/02-account-aware/01-team-plan/1"]}))
    (run / "bench.toml").write_text('models = ["vendor/model"]\n\n[run]\nmax_cost_usd = 1.5\n')
    name = "vendor-model/01-docs-qa/01-answer/after/1"
    (run / "calls.jsonl").write_text(json.dumps({"job": name, "call": 1, "status": 200, "error": None, "model": "vendor/model",
                                                 "answered_by": "vendor/model", "host": "SomeHost", "cost": 0.004, "ms": 1500,
                                                 "tokens": {"prompt": 283, "completion": 400, "reasoning": 100, "cached": 0},
                                                 "attempts": [{"status": 200, "ms": 1500}]}) + "\n")
    return run


GRADED = {"vendor-model/01-docs-qa/01-answer/after/1": [
    checks.Check("invariant", "payload_sent", True, ""), checks.Check("answer", "answered", True, ""),
    checks.Check("answer", "mentions_any", False, "mentions none of spam, junk"),
    checks.Check("grounding", "cites_of_the_articles_sent", None, "1 of 2")]}


def test_the_summary_holds_each_result_and_the_totals_by_model(tmp_path: Path) -> None:
    run = run_with(tmp_path)
    written = summary.write(run, GRADED)
    assert written == json.loads((run / "summary.json").read_text())
    [result] = [r for r in written["results"] if r["exit"] is not None]
    assert (result["case"], result["variant"], result["model"]) == ("01-docs-qa/01-answer", "after", "vendor/model")
    assert result["measures"] == {"invariant": [1, 1], "answer": [1, 2]}
    assert result["failed"] == ["answer mentions_any: mentions none of spam, junk"]
    assert "relevance-threshold" in result["constructs"]
    [not_run] = [r for r in written["results"] if r["exit"] is None]
    assert not_run["case"] == "02-account-aware/01-team-plan"
    model = written["models"]["vendor/model"]
    assert (model["done"], model["failed"], model["not_run"], model["calls"], model["cost"]) == (1, 0, 1, 1, 0.004)
    assert model["tokens"] == {"prompt": 283, "completion": 400, "reasoning": 100}
    assert model["measures"]["answer"] == [1, 2]
    # What the viewer reads for a result without listing folders: its checks, its assemblies and its answer.
    assert {"measure": "answer", "check": "mentions_any", "passed": False, "detail": "mentions none of spam, junk"} in result["checks"]
    assert result["assemblies"] == [f"{result['job']}/record"]
    assert result["answer"] == f"{result['job']}/record/run.json"
    assert written["max_cost_usd"] == 1.5
    case = {c["key"]: c for c in written["cases"]}["01-docs-qa/01-answer"]
    assert case["question"] == "Why didn't I get my password reset email?"
    assert list(case["snapshots"].values()) == [1]  # one snapshot digest across the run's results
    construct = {c["id"]: c for c in written["constructs"]}["relevance-threshold"]
    assert "01-docs-qa/01-answer" in construct["cases"] and construct["spec"] == ["R-13"]
    placement = {c["id"]: c for c in written["constructs"]}["placement-and-rendering"]
    assert placement["invariants"] == ["payload_sent"]


def test_the_index_lists_every_run_newest_first(tmp_path: Path) -> None:
    run = run_with(tmp_path)
    summary.write(run, GRADED)
    older = run.parent / "2026-10-01T090000Z-abc1234"
    shutil.copytree(run, older)
    summary.write(older, GRADED)
    index = summary.index(run.parent)
    assert [entry["run"] for entry in index["runs"]] == [run.name, older.name]
    assert index["runs"][0]["models"] == ["vendor/model"] and index["runs"][0]["spent"] == 0.004
    assert json.loads((run.parent / "index.json").read_text()) == index

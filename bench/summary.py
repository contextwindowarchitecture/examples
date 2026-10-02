"""A run's summary.json, which the viewer reads, and results/index.json, the list of runs. grade.py writes both.

summary.json holds, besides the manifest's commit, assembler pins and models:
  constructs  each construct: what it is, its requirements, the measures that show it, the cases that exercised it
  cases       each case: its question, the variants run (01's after and before), the constructs it exercised, and the
              snapshot digests its results froze, which in 01-03 is one per assembly whatever the model
  models      per model: jobs done, failed and not run; calls, cost, tokens, call latency and the hosts that answered;
              checks passed of those graded, by measure
  jobs        per job: how it ended, its calls, cost, tokens and hosts, and its checks by measure
  results     per case, model and repeat: its checks by measure, the checks it failed, the constructs it exercised and
              the folder that holds its record. 05's suite is one job and six results, one per eval case
"""
from __future__ import annotations

import json
import tomllib
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

import checks
import constructs
from checks import Check
from config import ROOT
from constructs import Facts


def facts(record: Path, example: str, steps: int) -> Facts:
    """What a result's assemblies show, from their traces and snapshots, and how many tool calls it tried."""
    reasons: set[str] = set()
    refusals: list[str] = []
    compressed = conflicts = tool_results = False
    made = checks.assemblies(record)
    for folder in made:
        trace = _read(folder / "trace.json")
        reasons |= {row["reason"] for row in trace["excluded"]}
        if trace["refused"]["bool"]:
            refusals.append(trace["refused"]["reason"])
        compressed |= bool(trace["compressed"])
        conflicts |= any(group["decided_by"] != "moot" for group in trace["conflicts"])
        admitted = {row["item_id"] for row in trace["included"]}
        tool_results |= any(item["slot"] == "evidence.tool_results" and item["id"] in admitted
                            for batch in _read(folder / "snapshot.json")["batches"] for item in batch["items"])
    return Facts(example, len(made), sum((folder / "payload.json").exists() for folder in made), frozenset(reasons),
                 tuple(refusals), compressed, conflicts, tool_results, steps)


def write(run: Path, graded: dict[str, list[Check]]) -> dict[str, Any]:
    manifest = _read(run / "manifest.json")
    model_of = {details["label"]: model for model, details in manifest["models"].items()}
    calls: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if (run / "calls.jsonl").exists():
        for line in (run / "calls.jsonl").read_text(encoding="utf-8").splitlines():
            calls[json.loads(line)["job"]].append(json.loads(line))
    jobs, results = [], []
    for name in manifest["jobs"]:
        label, example, *case, repeat = name.split("/")
        folder, model = run / name, model_of[label]
        ended = _read(folder / "job.json") if (folder / "job.json").exists() else None
        jobs.append(_job(name, model, example, "/".join(case), int(repeat), ended, calls[name], graded.get(name, [])))
        results += _results(folder, name, model, example, "/".join(case), int(repeat), ended, graded.get(name, []))

    cases: dict[str, dict[str, Any]] = {}
    for result in results:
        digest = result.pop("_digest")
        case = cases.setdefault(result["case"], {"key": result["case"], "question": _question(result["case"]),
                                                 "variants": [], "constructs": [], "snapshots": {}})
        if result["variant"] and result["variant"] not in case["variants"]:
            case["variants"].append(result["variant"])
        case["constructs"] += [c for c in result["constructs"] if c not in case["constructs"]]
        if digest:
            case["snapshots"][digest] = case["snapshots"].get(digest, 0) + 1

    written = {
        "run": run.name, "started": manifest["started"],  # a run is its folder, whatever was copied into it
        "graded": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "repository": manifest["repository"], "assembler": manifest["assembler"], "skipped": manifest["skipped"],
        "spent": round(sum(call["cost"] or 0 for lines in calls.values() for call in lines), 6),
        "max_cost_usd": tomllib.loads((run / "bench.toml").read_text(encoding="utf-8"))["run"]["max_cost_usd"]
        if (run / "bench.toml").exists() else None,
        "constructs": [{"id": c.id, "title": c.title, "spec": list(c.spec), "description": c.description,
                        "measures": list(c.measures), "invariants": list(c.invariants),
                        "cases": [key for key, case in cases.items() if c.id in case["constructs"]]}
                       for c in constructs.CONSTRUCTS],
        "cases": list(cases.values()),
        "models": {model: {**details, **_totals([job for job in jobs if job["model"] == model], calls)}
                   for model, details in manifest["models"].items()},
        "jobs": jobs,
        "results": results,
    }
    (run / "summary.json").write_text(json.dumps(written, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return written


def index(results: Path) -> dict[str, Any]:
    """Every graded run under results/, newest first, with what the run picker shows."""
    runs = []
    for path in sorted(results.glob("*/summary.json"), reverse=True):
        found = _read(path)
        models = found["models"].values()
        runs.append({"run": found["run"], "started": found["started"], "commit": found["repository"]["commit"],
                     "dirty": found["repository"]["dirty"], "assembler": sorted({p["tag"] for p in found["assembler"]}),
                     "models": list(found["models"]), "spent": found["spent"],
                     "done": sum(m["done"] for m in models), "failed": sum(m["failed"] for m in models),
                     "not_run": sum(m["not_run"] for m in models)})
    written = {"runs": runs}
    (results / "index.json").write_text(json.dumps(written, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return written


def _job(name: str, model: str, example: str, case: str, repeat: int, ended: dict[str, Any] | None,
         lines: list[dict[str, Any]], found: list[Check]) -> dict[str, Any]:
    answered = [line for line in lines if line["status"] == 200]
    return {"job": name, "model": model, "example": example, "case": case, "repeat": repeat,
            "exit": ended["exit"] if ended else None, "seconds": ended.get("seconds") if ended else None,
            "calls": len(lines), "cost": round(sum(line["cost"] or 0 for line in lines), 6),
            "tokens": _tokens(lines), "ms": [line["ms"] for line in answered],
            "hosts": dict(Counter(line["host"] for line in answered if line.get("host"))),
            "measures": _tally(found)}


def _results(folder: Path, name: str, model: str, example: str, case: str, repeat: int, ended: dict[str, Any] | None,
             found: list[Check]) -> list[dict[str, Any]]:
    scenario, _, variant = case.partition("/")
    base = {"model": model, "repeat": repeat, "job": name, "exit": ended["exit"] if ended else None}
    record = folder / "record"
    report = record / "report.json"
    if example == "05-production" and ended and ended["exit"] == 0 and report.exists():
        results = []
        for graded in _read(report)["cases"]:
            steps = len(_read(record / graded["id"] / "run.json").get("steps", []))
            failing = [f"evals {c['check']}: {c['detail']}" for c in graded["checks"] if not c["passed"]]
            results.append({**base, "case": f"05-production/{graded['id']}", "variant": None,
                            "record": f"{name}/record/{graded['id']}", "measures": {"evals": [int(graded["passed"]), 1]},
                            "failed": failing, "_digest": _digest(record / graded["id"]),
                            "checks": [{"measure": "evals", **check} for check in graded["checks"]],
                            "assemblies": _paths(name, folder, checks.turns(record / graded["id"])),
                            "answer": f"{name}/record/{graded['id']}/run.json", "request": None,
                            "constructs": constructs.exercised(facts(record / graded["id"], example, steps))})
        return results
    steps = len(_read(record / "run.json").get("steps", [])) if (record / "run.json").exists() else 0
    exercised = constructs.exercised(facts(record, example, steps)) if ended else []
    # Where the viewer finds what it shows, since a static server lists no folders.
    return [{**base, "case": f"{example}/{scenario}", "variant": variant or None, "record": f"{name}/record",
             "measures": {m: counts for m, counts in _tally(found).items()},
             "failed": [f"{c.measure} {c.check}: {c.detail}" for c in found if c.passed is False],
             "constructs": exercised, "_digest": _digest(record) if ended else None,
             "checks": [asdict(check) for check in found],
             "assemblies": _paths(name, folder, checks.assemblies(record)) if ended and record.exists() else [],
             "answer": f"{name}/record/run.json" if (record / "run.json").exists() else None,
             "request": f"{name}/record/request.json" if (record / "request.json").exists() else None}]


def _paths(name: str, folder: Path, found: list[Path]) -> list[str]:
    """Folders under a job, as paths from the run's folder."""
    return [f"{name}/{path.relative_to(folder).as_posix()}" for path in found]


def _totals(jobs: list[dict[str, Any]], calls: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    lines = [line for job in jobs for line in calls[job["job"]]]
    ms = [m for job in jobs for m in job["ms"]]
    measures: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for job in jobs:
        for measure, (passed, graded) in job["measures"].items():
            measures[measure][0] += passed
            measures[measure][1] += graded
    hosts: Counter[str] = Counter()
    for job in jobs:
        hosts.update(job["hosts"])
    return {"done": sum(job["exit"] == 0 for job in jobs), "not_run": sum(job["exit"] is None for job in jobs),
            "failed": sum(job["exit"] not in (0, None) for job in jobs), "calls": len(lines),
            "cost": round(sum(line["cost"] or 0 for line in lines), 6), "tokens": _tokens(lines),
            "ms": {"median": median(ms) if ms else None, "most": max(ms) if ms else None},
            "hosts": dict(hosts), "measures": dict(measures)}


def _tally(found: list[Check]) -> dict[str, list[int]]:
    measures: dict[str, list[int]] = {}
    for check in found:
        if check.passed is not None:
            counts = measures.setdefault(check.measure, [0, 0])
            counts[0] += check.passed
            counts[1] += 1
    return measures


def _tokens(lines: list[dict[str, Any]]) -> dict[str, int]:
    return {kind: sum((line.get("tokens") or {}).get(kind) or 0 for line in lines)
            for kind in ("prompt", "completion", "reasoning")}


def _digest(record: Path) -> str | None:
    """The first assembly's snapshot digest: in 01-03 the scenario's own, whatever the model."""
    made = checks.assemblies(record) if record.exists() else []
    return _read(made[0] / "trace.json")["context"]["snapshot_digest"][:12] if made else None


def _question(key: str) -> str:
    example, case = key.split("/", 1)
    folder = ROOT / example
    if example == "05-production":
        return next((c["question"] for c in _read(folder / "evals" / "cases.json")["cases"] if c["id"] == case), "")
    for name in ("conversation.json", "scenario.json"):
        if (folder / "scenarios" / case / name).exists():
            return _read(folder / "scenarios" / case / name)["question"]
    return ""


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

"""The agent's evals: run the suite against a model, grade each answer against what its run actually did, and promote
the route's profile only when every case passes (R-19).

    uv run evals.py run --provider openai                  # run every case live, record it, grade the results
    uv run evals.py grade evals/results/LABEL              # grade recorded results again; --check fails when the
                                                             committed report differs
    uv run evals.py promote evals/results/LABEL            # mark the profile evaluated, if every case passed for
                                                             this exact profile and the model it names

A run is recorded like an agent scenario: scenario.json, every inference's snapshot, trace and payload, and run.json.
The results are an artifact: graded from the files alone, without a model, so anyone can reproduce the report and a
profile's evaluation can point at it.

Every case is checked for:
  answered              the run ended with an answer
  cites_what_it_was_sent  every help-center id the answer cites was in the request that produced it
  claims_match_actions  the answer says it enabled or deleted a webhook exactly when the run did
and for its own expectations: must_call, must_not_call, must_cite, mentions_any, mentions_none.

The claim checks read the answer with patterns, so they are cheap and reproducible, and they are heuristics. A model
used as a judge, given the run record, catches what the patterns miss.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from cwa.registry import profile_digest

import agent
import routes
import store
from conversation import Conversation

HERE = Path(__file__).parent
CASES = HERE / "evals" / "cases.json"
RESULTS = HERE / "evals" / "results"
PROFILE = HERE / "policy" / "account-agent" / "profile.json"

CITATION = re.compile(r"help:[a-z0-9-]+@\d+#\d+")
# First-person or completed-state claims of a state change, per tool that makes one.
CLAIMS = {
    "enable_webhook": re.compile(r"\bI(?:'ve| have)? (?:re-?enabled|enabled|turned \S+(?: \S+)? back on|switched \S+ back on|reactivated)\b"
                                 r"|\b(?:has been|was) re-?enabled\b|\bis (?:now )?active again\b", re.IGNORECASE),
    "delete_webhook": re.compile(r"\bI(?:'ve| have)? (?:deleted|removed)\b|\b(?:has been|was) deleted\b", re.IGNORECASE),
}


@dataclass(frozen=True)
class Check:
    check: str
    passed: bool
    detail: str


def ran(steps: list[dict[str, Any]]) -> set[str]:
    """The tools the run actually called, successfully."""
    return {step["tool"] for step in steps if step["approved"] and step["ok"]}


def grade(case: dict[str, Any], run: dict[str, Any], final_trace: dict[str, Any] | None) -> list[Check]:
    answer, steps, expect = run["answer"] or "", run["steps"], case.get("expect", {})
    called = ran(steps)
    checks = [Check("answered", run["answer"] is not None,
                    "answered" if run["answer"] is not None else f"no answer: {run['refused'] or 'out of turns'}")]
    sent = {row["item_id"] for row in (final_trace or {}).get("included", []) if row["slot"] == "evidence.knowledge"}
    unsent = sorted(set(CITATION.findall(answer)) - sent)
    checks.append(Check("cites_what_it_was_sent", not unsent,
                        f"cites articles the request did not send: {', '.join(unsent)}" if unsent else "every citation was sent"))
    mismatches = []
    for tool, pattern in CLAIMS.items():
        claimed = pattern.search(answer)
        if claimed and tool not in called:
            mismatches.append(f"says '{claimed.group(0)}' but {tool} did not run")
        if tool in called and not claimed:
            mismatches.append(f"{tool} ran but the answer does not say so")
    checks.append(Check("claims_match_actions", not mismatches, "; ".join(mismatches) or "claims match the run"))
    for tool in expect.get("must_call", []):
        checks.append(Check(f"must_call {tool}", tool in called, "called" if tool in called else "not called"))
    for tool in expect.get("must_not_call", []):
        checks.append(Check(f"must_not_call {tool}", tool not in called, "not called" if tool not in called else "called"))
    for citation in expect.get("must_cite", []):
        checks.append(Check(f"must_cite {citation}", citation in answer, "cited" if citation in answer else "not cited"))
    if "mentions_any" in expect:
        found = [term for term in expect["mentions_any"] if term.lower() in answer.lower()]
        checks.append(Check("mentions_any", bool(found), f"mentions {', '.join(found)}" if found else
                            f"mentions none of {', '.join(expect['mentions_any'])}"))
    if "mentions_none" in expect:
        found = [term for term in expect["mentions_none"] if term.lower() in answer.lower()]
        checks.append(Check("mentions_none", not found, f"mentions {', '.join(found)}" if found else "clean"))
    return checks


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def report(results: Path) -> dict[str, Any]:
    """Grade recorded results from their files alone."""
    suite = _json(CASES)
    meta = _json(results / "meta.json")
    cases = []
    for case in suite["cases"]:
        folder = results / case["id"]
        turns = sorted(folder.glob("turn-*"), key=lambda path: int(path.name.split("-")[1]))
        final_trace = _json(turns[-1] / "trace.json") if turns else None
        checks = grade(case, _json(folder / "run.json"), final_trace)
        cases.append({"id": case["id"], "passed": all(check.passed for check in checks),
                      "checks": [check.__dict__ for check in checks]})
    passed = sum(case["passed"] for case in cases)
    return {**meta, "suite": suite["suite"], "result": f"{passed} of {len(cases)} cases passed", "cases": cases}


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_suite(provider: str, model_name: str | None, label: str | None) -> Path:
    """Run every case live against the route's model (or model_name), and record each run."""
    route = routes.load(routes.default())
    options = {"model": model_name} if model_name else dict(route.models[provider])
    profile = _json(PROFILE)
    results = RESULTS / (label or f"{options['model']}-{date.today().isoformat()}")
    results.mkdir(parents=True, exist_ok=True)
    _write(results / "meta.json", {
        "model": options["model"], "date": date.today().isoformat(),
        "profile": {"id": profile["id"], "version": profile["version"], "sha256": profile_digest(profile)},
        "route_policy": route.policy["version"]})
    users = _json(agent.ACCOUNTS)["users"]
    with store.connect() as db:
        for case in _json(CASES)["cases"]:
            print(f"{case['id']} ...", flush=True)
            conversation = Conversation.new(users[case["user"]]["workspace"], case["user"])
            conversation.faults = list(case.get("faults", []))
            conversation.ask(case["question"])
            model = agent.LiveModel(provider, options, route.budget["reserved_output"])
            clock = agent.Clock()
            outcome = asyncio.run(agent.run(conversation, route, model, clock, io.StringIO()))
            store.save(db, f"t_{conversation.session}", conversation.asked_at, conversation.workspace, conversation.user,
                       conversation.question, model.name, outcome)
            agent.record(results / case["id"], conversation, model, clock)
            agent.save(results / case["id"], outcome)
    return results


def _artifact(path: Path) -> str:
    """Where the evaluation's evidence is: relative to the example when it is inside it (R-19)."""
    path = path.resolve()
    return str(path.relative_to(HERE)) if path.is_relative_to(HERE) else str(path)


def promote(results: Path) -> list[str]:
    """Mark the profile evaluated with these results as its artifact, or say why not (R-19). Only the evaluation
    changes, so the profile keeps its version and its lock entry (R-20)."""
    graded, profile = report(results), _json(PROFILE)
    problems = []
    if graded["profile"]["sha256"] != profile_digest(profile):
        problems.append(f"the results are for a different profile (sha256 {graded['profile']['sha256'][:12]}); run the suite again")
    if graded["model"] != profile["model_family"]:
        problems.append(f"the results are for {graded['model']}, the profile names {profile['model_family']}")
    failed = [case["id"] for case in graded["cases"] if not case["passed"]]
    if failed:
        problems.append(f"{graded['result']}; failing: {', '.join(failed)}")
    if not problems:
        profile["evaluation"] = {"status": "evaluated", "suite": graded["suite"], "date": graded["date"],
                                 "result": graded["result"], "artifact": _artifact(results / "report.json")}
        _write(PROFILE, profile)
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    running = commands.add_parser("run")
    running.add_argument("--provider", choices=["anthropic", "openai"], default="openai")
    running.add_argument("--model", help="the model to evaluate, on the endpoint the environment names; default the route's")
    running.add_argument("--label", help="the results folder's name under evals/results/")
    grading = commands.add_parser("grade")
    grading.add_argument("results")
    grading.add_argument("--check", action="store_true", help="fail when the committed report.json differs")
    commands.add_parser("promote").add_argument("results")
    args = parser.parse_args(argv)
    if args.command == "run":
        results = run_suite(args.provider, args.model, args.label)
    elif args.command == "promote":
        problems = promote(Path(args.results))
        print("promoted: the profile is evaluated" if not problems else "not promoted:\n  " + "\n  ".join(problems))
        return 0 if not problems else 1
    else:
        results = Path(args.results)
    graded = report(results)
    if args.command == "grade" and args.check:
        current = _json(results / "report.json") if (results / "report.json").exists() else None
        if current != graded:
            print(f"{results / 'report.json'} is stale: run `uv run evals.py grade {results}`", file=sys.stderr)
            return 1
    else:
        _write(results / "report.json", graded)
    for case in graded["cases"]:
        print(f"{'pass' if case['passed'] else 'FAIL'}  {case['id']}")
        for check in case["checks"]:
            if not check["passed"]:
                print(f"        {check['check']}: {check['detail']}")
    print(f"{graded['result']} ({graded['model']}, profile {graded['profile']['id']} v{graded['profile']['version']})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""The snapshot store: every inference the agent makes, kept so any answer can be explained, replayed and re-decided.

A snapshot holds everything that decided a request (R-23), so storing it, not the prompt, is what makes an answer
debuggable later. Snapshots are stored once, by their digest; runs, inferences and tool calls point at them.

    uv run store.py runs                                  # the stored runs, newest first
    uv run store.py show RUN                              # one run: each inference's decisions, each tool call, the answer
    uv run store.py replay RUN                            # re-assemble every stored snapshot; same bytes, or a finding
    uv run store.py whatif DIR [--run RUN]                # re-decide stored snapshots under the route policy and profile
                                                            in DIR, and show what would change, before shipping DIR

The store is a SQLite file, store/cwa.sqlite by default, or DOCS_QA_STORE. It holds what users asked and what the
application knew about them, so give it the retention and access rules of the data in it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, TextIO

import context
import report

DEFAULT = Path(__file__).parent / "store" / "cwa.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (digest TEXT PRIMARY KEY, document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, workspace TEXT NOT NULL, user TEXT NOT NULL,
    question TEXT NOT NULL, model TEXT NOT NULL, answer TEXT, refused TEXT);
CREATE TABLE IF NOT EXISTS inferences (
    run_id TEXT NOT NULL REFERENCES runs, turn INTEGER NOT NULL,
    snapshot TEXT NOT NULL REFERENCES snapshots, payload_sha256 TEXT, input_tokens INTEGER, refused TEXT,
    route_policy TEXT NOT NULL, profile TEXT NOT NULL, trace TEXT NOT NULL,
    PRIMARY KEY (run_id, turn));
CREATE TABLE IF NOT EXISTS steps (
    run_id TEXT NOT NULL REFERENCES runs, n INTEGER NOT NULL, tool TEXT NOT NULL, arguments TEXT NOT NULL,
    approved INTEGER NOT NULL, reason TEXT NOT NULL, ok INTEGER, value TEXT, observed_at TEXT,
    PRIMARY KEY (run_id, n));
"""


def path() -> Path:
    return Path(os.environ.get("DOCS_QA_STORE", DEFAULT))


def connect(location: Path | None = None) -> sqlite3.Connection:
    location = location or path()
    location.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(location)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def save(db: sqlite3.Connection, run_id: str, started_at: str, workspace: str, user: str, question: str, model: str,
         outcome: Any) -> None:
    """Store one agent run (agent.Run): its snapshots, once each, its inferences, its tool calls and its answer."""
    with db:
        db.execute("INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (run_id, started_at, workspace, user, question, model, outcome.answer, outcome.refused))
        for number, inference in enumerate(outcome.inferences, start=1):
            trace = inference.result.trace
            digest = trace["context"]["snapshot_digest"]
            db.execute("INSERT OR IGNORE INTO snapshots VALUES (?, ?)", (digest, json.dumps(inference.document, sort_keys=True)))
            result = trace["result"] or {}
            db.execute("INSERT OR REPLACE INTO inferences VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (run_id, number, digest, result.get("hash"), result.get("input_tokens"), trace["refused"]["reason"],
                        trace["context"]["route_policy_version"], f"{trace['profile']['id']} v{trace['profile']['version']}",
                        json.dumps(trace, sort_keys=True)))
        for n, step in enumerate(outcome.steps, start=1):
            db.execute("INSERT OR REPLACE INTO steps VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (run_id, n, step.tool, json.dumps(step.arguments, sort_keys=True), int(step.approved), step.reason,
                        None if step.ok is None else int(step.ok), json.dumps(step.value, sort_keys=True), step.observed_at))


def snapshots(db: sqlite3.Connection, run_id: str | None = None) -> Iterator[tuple[str, int, dict[str, Any], sqlite3.Row]]:
    """(run_id, turn, snapshot, inference row) for one run, or for every stored inference."""
    query = ("SELECT i.*, s.document FROM inferences i JOIN snapshots s ON s.digest = i.snapshot"
             + (" WHERE i.run_id = ?" if run_id else "") + " ORDER BY i.run_id, i.turn")
    for row in db.execute(query, (run_id,) if run_id else ()):
        yield row["run_id"], row["turn"], json.loads(row["document"]), row


@dataclass(frozen=True)
class Replayed:
    run_id: str
    turn: int
    same: bool
    before: str | None  # the stored payload hash, or the refusal
    after: str | None


def replay(db: sqlite3.Connection, run_id: str) -> list[Replayed]:
    """Re-assemble every stored snapshot of a run. The same snapshot must give the same bytes (R-23): a difference is
    an assembler or tokenizer change, never something to normalize away."""
    found = []
    for run, turn, document, row in snapshots(db, run_id):
        result = context.assemble(document)
        before = row["payload_sha256"] or f"refused: {row['refused']}"
        after = hashlib.sha256(result.payload).hexdigest() if result.payload is not None else f"refused: {result.trace['refused']['reason']}"
        found.append(Replayed(run, turn, before == after, before, after))
    return found


@dataclass(frozen=True)
class Difference:
    run_id: str
    turn: int
    changes: list[str]


def decisions(trace: dict[str, Any]) -> dict[str, str]:
    """Every candidate's fate in a trace: sent, summarized, or left out with its reason."""
    compressed = {row["item_id"] for row in trace["compressed"]}
    fates = {row["item_id"]: "summarized" if row["item_id"] in compressed else "sent" for row in trace["included"]}
    fates.update({row["item_id"]: row["reason"] for row in trace["excluded"]})
    return fates


def whatif(db: sqlite3.Connection, route_policy: dict[str, Any], profile: dict[str, Any],
           run_id: str | None = None) -> list[Difference]:
    """Re-decide stored snapshots under a candidate route policy and profile, and list what changes per inference:
    an item's fate, a refusal, or the request's size. Nothing is sent to a model."""
    differences = []
    for run, turn, document, row in snapshots(db, run_id):
        old = json.loads(row["trace"])
        new = context.assemble({**document, "route_policy": route_policy, "profile": profile}).trace
        before, after = decisions(old), decisions(new)
        changes = [f"{item}: {before.get(item, 'absent')} -> {after.get(item, 'absent')}"
                   for item in sorted(set(before) | set(after)) if before.get(item) != after.get(item)]
        if old["refused"] != new["refused"]:
            changes.append(f"refused: {old['refused']['reason']} -> {new['refused']['reason']}")
        if (old["result"] or {}).get("input_tokens") != (new["result"] or {}).get("input_tokens"):
            changes.append(f"input tokens: {(old['result'] or {}).get('input_tokens')} -> {(new['result'] or {}).get('input_tokens')}")
        if changes:
            differences.append(Difference(run, turn, changes))
    return differences


def show(db: sqlite3.Connection, run_id: str, out: TextIO = sys.stdout) -> None:
    run = db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise SystemExit(f"no run {run_id}")
    print(f"{run['run_id']}  {run['started_at']}  {run['user']} of {run['workspace']}  {run['model']}\n{run['question']}", file=out)
    for _, turn, document, row in snapshots(db, run_id):
        print(f"\nturn {turn}", file=out)
        report.report(document, _Result(json.loads(row["trace"])), out)
    for step in db.execute("SELECT * FROM steps WHERE run_id = ? ORDER BY n", (run_id,)):
        verdict = "called" if step["approved"] else f"denied: {step['reason']}"
        print(f"  > {step['tool']} {step['arguments']}: {verdict}", file=out)
    print(f"\n{run['answer'] if run['answer'] is not None else 'no answer: ' + str(run['refused'])}", file=out)


@dataclass(frozen=True)
class _Result:
    """A stored trace, shaped like an AssemblyResult for report.report()."""
    trace: dict[str, Any]
    payload: None = None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("runs")
    commands.add_parser("show").add_argument("run")
    commands.add_parser("replay").add_argument("run")
    candidate = commands.add_parser("whatif")
    candidate.add_argument("policy", help="a folder holding the candidate route-policy.json and profile.json")
    candidate.add_argument("--run", help="only this run; default every stored inference")
    args = parser.parse_args(argv)
    db = connect()
    if args.command == "runs":
        for run in db.execute("SELECT * FROM runs ORDER BY started_at DESC"):
            outcome = "answered" if run["answer"] is not None else f"no answer ({run['refused'] or 'out of turns'})"
            print(f"{run['run_id']}  {run['started_at']}  {run['user']:<6} {outcome:<10} {run['question'][:60]}")
    elif args.command == "show":
        show(db, args.run)
    elif args.command == "replay":
        found = replay(db, args.run)
        for item in found:
            print(f"turn {item.turn}: " + ("same" if item.same else f"DIFFERENT {item.before} -> {item.after}"))
        return 0 if found and all(item.same for item in found) else 1
    else:
        folder = Path(args.policy)
        policy = json.loads((folder / "route-policy.json").read_text(encoding="utf-8"))
        profile = json.loads((folder / "profile.json").read_text(encoding="utf-8"))
        differences = whatif(db, policy, profile, args.run)
        for difference in differences:
            print(f"{difference.run_id} turn {difference.turn}")
            for change in difference.changes:
                print(f"  {change}")
        print(f"{len(differences)} inferences would change")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

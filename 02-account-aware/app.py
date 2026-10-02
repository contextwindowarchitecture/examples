"""The help-center bot from 01, now aware of who is asking: their workspace's plan and their role, from the accounts
database, and what they told it before, from the memory store. app.py is 01's after.py; the new producers and the
conflict groups are in producers.py and context.py.

    uv run app.py "Can we turn on single sign-on?"                               # as u_ada; prints decisions and request
    uv run app.py --user u_cho "Can we turn on single sign-on?"
    uv run app.py --conversation scenarios/02-memory-disagrees/conversation.json
    uv run app.py --replay runs/<digest>/snapshot.json                          # re-assemble a saved request
    uv run --env-file .env app.py --provider anthropic "Can we turn on single sign-on?"

Every assembly is saved under runs/<digest>/ as snapshot.json, trace.json and, unless refused, payload.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TextIO

from cwa import AssemblyResult

import cli
import context
import providers
from conversation import Conversation

RUNS = Path(__file__).parent / "runs"


def build_request(conversation: Conversation) -> tuple[dict[str, Any], AssemblyResult]:
    document = context.snapshot(conversation)  # freeze: what each producer proposed, the route's policy, the clock
    return document, context.assemble(document)  # decide: admission, fitting, rendering; no I/O, no model call


def answer(conversation: Conversation, provider: str, model: str | None, *,
           out: TextIO = sys.stdout, runs: Path = RUNS) -> str | None:
    document, result = build_request(conversation)
    save(document, result, runs)
    report(document, result, out)
    if result.payload is None:
        return None  # refused: there is no payload, so nothing can reach a model (R-17)
    payload = json.loads(result.payload)  # cwa-messages/v1: {"system": [...], "tools": [...], "messages": [one user message]}
    system = [entry["text"] for entry in payload["system"]]
    messages = payload["messages"]
    if provider == "none":
        cli.show_request(system, messages, out)
        return None
    return providers.ask(provider, model, system, messages, context.reserved_output())


def report(document: dict[str, Any], result: AssemblyResult, out: TextIO = sys.stdout) -> None:
    """The trace as a table: one row per candidate item, sent (+) or left out (-) with its reason, and one row per
    declared conflict group (!) with what decided it."""
    trace = result.trace
    candidates = {item["id"]: item for batch in document["batches"] for item in batch["items"]}
    # Items a producer dropped itself never reach the snapshot as candidates; their rows name the producer instead.
    reported_by = {row["item_id"]: batch["producer"]["id"] for batch in document["batches"] for row in batch["excluded"]}

    def score(item_id: str) -> str:
        relevance = candidates.get(item_id, {}).get("relevance")
        return "" if relevance is None else f"  relevance {relevance:g}"

    if trace["refused"]["bool"]:
        recovery = (trace.get("recovery") or {}).get("action")
        print(f"refused: {trace['refused']['reason']}" + (f", recovery {recovery}" if recovery else "")
              + ". No request is sent.", file=out)
    else:
        budget = trace["budget"]
        margin = f" with a {budget['margin_percent']}% margin" if budget.get("margin_percent") else ""
        print(f"assembled {trace['profile']['id']} v{trace['profile']['version']}: {trace['result']['input_tokens']} "
              f"input tokens of {budget['input']}{margin}, sha256 {trace['result']['hash'][:12]}", file=out)
    for row in trace["included"]:
        print(f"  + {row['slot']:<24} {row['item_id']:<28} {row['tokens']:>4} tokens{score(row['item_id'])}", file=out)
    for row in trace["excluded"]:
        if row["stage"] == "producer":
            where = f"(by {reported_by.get(row['item_id'], 'producer')})"
        else:
            where = row.get("slot") or candidates.get(row["item_id"], {}).get("slot", "")
        print(f"  - {where:<24} {row['item_id']:<28} {row['reason']}{score(row['item_id'])}", file=out)
    for group in trace["conflicts"]:
        if group["decided_by"] == "moot":
            outcome = "moot, fewer than two members admitted"
        else:
            outcome = f"decided by {group['decided_by']}, " + (f"{group['winner']} prevails" if group.get("winner")
                                                                else group["resolution"])
        print(f"  ! {group['group_id']:<24} {', '.join(group['items'])}: {outcome}", file=out)


def save(document: dict[str, Any], result: AssemblyResult, runs: Path = RUNS) -> Path:
    """Keep the frozen input with its outcome, keyed by the snapshot digest: enough to replay this exact request."""
    directory = runs / result.trace["context"]["snapshot_digest"][:16]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "snapshot.json").write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (directory / "trace.json").write_text(json.dumps(result.trace, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if result.payload is not None:
        (directory / "payload.json").write_bytes(result.payload)
    return directory


def replay(path: str | Path, out: TextIO = sys.stdout) -> bool:
    """Re-assemble a saved snapshot and compare the outcome with the trace saved beside it."""
    path = Path(path)
    document = json.loads(path.read_text(encoding="utf-8"))
    result = context.assemble(document)
    report(document, result, out)
    saved = path.with_name("trace.json")
    if not saved.exists():
        return True
    before = json.loads(saved.read_text(encoding="utf-8"))
    same = before["result"] == result.trace["result"] and before["refused"] == result.trace["refused"]
    print("replay: same outcome, byte for byte" if same else "replay: the outcome differs from the saved trace", file=out)
    return same


def main(argv: list[str]) -> int:
    parser = cli.parser(__doc__)
    parser.add_argument("--replay", metavar="SNAPSHOT", help="re-assemble a saved snapshot.json and compare it with its trace")
    args = parser.parse_args(argv)
    if args.replay:
        return 0 if replay(args.replay) else 1
    return cli.run(args, answer)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""The same help-center bot with CWA. The producers propose context, the assembler decides what is sent, and the trace
records every decision. A question the help center cannot answer is refused before any model is called.
Compare build_request() with the one in before.py.

    uv run after.py "How do I export all my projects?"                           # prints the decisions and the request
    uv run after.py --conversation scenarios/02-long-conversation/conversation.json
    uv run after.py --replay runs/<digest>/snapshot.json                        # re-assemble a saved request
    uv run --env-file .env after.py --provider anthropic "How do I export all my projects?"
    uv run --env-file .env after.py --provider anthropic --record runs/export "How do I export all my projects?"

Every assembly is saved under runs/<digest>/ as snapshot.json, trace.json and, unless refused, payload.json. --record DIR
also writes them to DIR, with the conversation (conversation.json) and the reply (run.json).
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
           out: TextIO = sys.stdout, runs: Path = RUNS, record: str | Path | None = None) -> str | None:
    document, result = build_request(conversation)
    save(document, result, runs)
    if record:
        write(Path(record), document, result)  # --record: this assembly, beside the conversation and the reply
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
    """The trace as a table: one row per candidate item, sent (+) or left out (-) with its reason."""
    trace = result.trace
    candidates = {item["id"]: item for batch in document["batches"] for item in batch["items"]}

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
        slot = row.get("slot") or candidates.get(row["item_id"], {}).get("slot", "")
        print(f"  - {slot:<24} {row['item_id']:<28} {row['reason']}{score(row['item_id'])}", file=out)


def save(document: dict[str, Any], result: AssemblyResult, runs: Path = RUNS) -> Path:
    """Keep the frozen input with its outcome, keyed by the snapshot digest: enough to replay this exact request."""
    directory = runs / result.trace["context"]["snapshot_digest"][:16]
    write(directory, document, result)
    return directory


def write(directory: Path, document: dict[str, Any], result: AssemblyResult) -> None:
    """snapshot.json, trace.json and, unless the assembly refused, payload.json."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "snapshot.json").write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (directory / "trace.json").write_text(json.dumps(result.trace, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if result.payload is not None:
        (directory / "payload.json").write_bytes(result.payload)


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


def main(argv: list[str], *, runs: Path = RUNS) -> int:
    parser = cli.parser(__doc__)
    parser.add_argument("--replay", metavar="SNAPSHOT", help="re-assemble a saved snapshot.json and compare it with its trace")
    args = parser.parse_args(argv)
    if args.replay:
        return 0 if replay(args.replay) else 1
    return cli.run(args, lambda conversation, provider, model: answer(conversation, provider, model, runs=runs,
                                                                       record=args.record))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

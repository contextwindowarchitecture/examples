"""The account-aware bot from 02 on two model routes. The application tries the small route first; when that route's
budget cannot hold what must be sent, it rebuilds the snapshot for the large route. Under budget pressure, long
history turns and long articles are replaced by summaries written ahead of time, before anything is dropped.

    uv run app.py "How do I export the whole workspace?"                         # small route, as u_ada
    uv run app.py --route account-help "How do I export the whole workspace?"    # the large route
    uv run app.py --conversation scenarios/02-small-route/conversation.json
    uv run app.py --replay runs/<digest>/snapshot.json                          # re-assemble a saved request
    uv run --env-file .env app.py --provider anthropic "How do I export the whole workspace?"
    uv run --env-file .env app.py --provider anthropic --record runs/export "How do I export the whole workspace?"

Every assembly is saved under runs/<digest>/ as snapshot.json, trace.json and, unless refused, payload.json. --record DIR
also writes each route's assembly to DIR/<route>/, with the conversation (conversation.json) and the reply (run.json).
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
import routes
import summarize
from conversation import Conversation
from routes import Route

RUNS = Path(__file__).parent / "runs"


def build_request(conversation: Conversation, route: Route) -> tuple[dict[str, Any], AssemblyResult]:
    document = context.snapshot(conversation, route)  # freeze: what each producer proposed, the route's policy, the clock
    return document, context.assemble(document)  # decide: admission, fitting, rendering; no I/O, no model call


def answer(conversation: Conversation, provider: str, model: str | None, *, route: str | None = None,
           out: TextIO = sys.stdout, runs: Path = RUNS, record: str | Path | None = None) -> str | None:
    chosen = routes.load(route or conversation.route or routes.default())
    tried = []
    while True:
        document, result = build_request(conversation, chosen)
        save(document, result, runs)
        if record:
            write(Path(record) / chosen.name, document, result)  # --record: one folder per route tried
        print(f"route {chosen.name}", file=out)
        report(document, result, out)
        if result.payload is not None:
            break
        # Refused: there is no payload, so nothing can reach a model (R-17). The application's recovery for this route
        # and reason may be another route, which means a new snapshot, never a trimmed payload (R-12).
        tried.append(chosen.name)
        escalate_to = chosen.escalation(result.trace["refused"]["reason"])
        if escalate_to is None or escalate_to in tried:
            return None
        print(f"\nescalating to route {escalate_to}\n", file=out)
        chosen = routes.load(escalate_to)
    payload = json.loads(result.payload)  # cwa-messages/v1: {"system": [...], "tools": [...], "messages": [one user message]}
    system = [entry["text"] for entry in payload["system"]]
    messages = payload["messages"]
    if provider == "none":
        cli.show_request(system, messages, out)
        return None
    if provider not in chosen.models:
        raise providers.ProviderError(f"route {chosen.name} names no {provider} model in policy/routes.json")
    # --model replaces the route's settings for the provider, endpoint included: that model, on the endpoint the
    # environment names (OPENAI_BASE_URL), whichever route answers. The route still decides the budget and the policy.
    options = {"model": model} if model else dict(chosen.models[provider])
    return providers.ask(provider, options, system, messages, chosen.budget["reserved_output"])


def save_turn(conversation: Conversation, reply: str, provider: str) -> None:
    """Save the question and the answer to the history, each with a summary if it is long. The summary is made now,
    when the turn is written, so a later assembly can choose it without calling a model (R-18)."""
    options = dict(routes.load(routes.default()).models[provider])
    summaries = tuple(
        {"method": summarize.method(options), "text": summarize.summarize(text, provider, options)}
        if summarize.needs_summary(text) else None
        for text in (conversation.question, reply)
    )
    conversation.answered(reply, summaries)  # type: ignore[arg-type]


def report(document: dict[str, Any], result: AssemblyResult, out: TextIO = sys.stdout) -> None:
    """The trace as a table: one row per candidate item, sent whole (+), sent as a summary (~) or left out (-) with its
    reason, and one row per declared conflict group (!) with what decided it."""
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
    compressed = {row["item_id"]: row for row in trace["compressed"]}
    for row in trace["included"]:
        if row["item_id"] in compressed:  # sent as a variant: ~ marks it, with the original's size
            shrunk = compressed[row["item_id"]]
            print(f"  ~ {row['slot']:<24} {row['item_id']:<28} {row['tokens']:>4} tokens, summary of {shrunk['from']}"
                  f"{score(row['item_id'])}", file=out)
        else:
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
    parser.add_argument("--route", choices=routes.names(), help=f"the route to try first (default: {routes.default()})")
    parser.add_argument("--replay", metavar="SNAPSHOT", help="re-assemble a saved snapshot.json and compare it with its trace")
    args = parser.parse_args(argv)
    if args.replay:
        return 0 if replay(args.replay) else 1
    return cli.run(args, lambda conversation, provider, model: answer(conversation, provider, model, route=args.route,
                                                                       runs=runs, record=args.record), save_turn)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

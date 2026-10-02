"""The trace as a table: what the assembler sent, in what form, and what it left out and why."""
from __future__ import annotations

import sys
from typing import Any, TextIO

from cwa import AssemblyResult


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

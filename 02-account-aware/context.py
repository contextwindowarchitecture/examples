"""Freeze one request's context into a snapshot, and assemble it.

The snapshot holds everything that can change the request: the producers' batches, the conflict groups the
application declares, the route policy, the placement profile, the budget, the tokenizer and renderer, the request's
scope and the clock. assemble() reads nothing else and calls no model, so a stored snapshot replays to the same bytes
on any machine (R-23).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cwa import AssemblyResult, Snapshot
from cwa import assemble as cwa_assemble

import producers
from conversation import Conversation

POLICY = Path(__file__).parent / "policy"


def _policy(name: str) -> Any:
    return json.loads((POLICY / name).read_text(encoding="utf-8"))


def conflict_groups(facts: producers.Facts) -> list[dict[str, Any]]:
    """One fact group per fact that two or more items assert, such as an account's plan and a memory about it. The
    route policy's facts decide each group by producer; the assembler never compares the bodies (R-11)."""
    claims: dict[str, list[str]] = {}
    for item_id, fact in facts.items():
        claims.setdefault(fact, []).append(item_id)
    return [{"id": f"fact:{fact}", "kind": "fact", "fact": fact, "items": sorted(ids)}
            for fact, ids in sorted(claims.items()) if len(ids) >= 2]


def snapshot(conversation: Conversation) -> dict[str, Any]:
    """Run the producers for this question and freeze what they proposed with the route's policy (snapshot.schema.json)."""
    settings = _policy("assembly.json")
    accounts, account_facts = producers.accounts_db(conversation)
    memories, memory_facts = producers.memory_store(conversation)
    return {
        "assembly_time": conversation.asked_at,
        # Who is asking. An item that carries a scope key with another value is excluded, whoever produced it (R-2).
        "scope": {"tenant": conversation.workspace, "user": conversation.user, "session": conversation.session},
        "budget": settings["budget"],
        "profile": _policy("profile.json"),
        "route_policy": _policy("route-policy.json"),
        "tokenizer": settings["tokenizer"],
        "renderer": settings["renderer"],
        "batches": [
            producers.app_policy(),
            accounts,
            memories,
            producers.help_center_search(conversation.question, settings["retrieval"]["top_k"]),
            producers.chat_session(conversation),
        ],
        "conflicts": conflict_groups(account_facts | memory_facts),
    }


def assemble(document: dict[str, Any]) -> AssemblyResult:
    """Admission, conflict resolution, fitting and rendering: the payload to send, or none, and the trace that says why."""
    return cwa_assemble(Snapshot.from_json(document))


def reserved_output() -> int:
    """The output the route reserves; the input budget is what remains of the model's context (R-16)."""
    return _policy("assembly.json")["budget"]["reserved_output"]

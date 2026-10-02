"""Freeze one request's context into a snapshot for a route, and assemble it.

The snapshot holds everything that can change the request: the producers' batches, the conflict groups the
application declares, the route's policy and placement profile, its budget, tokenizer and renderer, the request's
scope and the clock. assemble() reads nothing else and calls no model, so a stored snapshot replays to the same bytes
on any machine (R-23). The same producers feed every route; only the route's half of the snapshot differs.
"""
from __future__ import annotations

from typing import Any

from cwa import AssemblyResult, Snapshot
from cwa import assemble as cwa_assemble

import producers
from conversation import Conversation
from routes import Route


def conflict_groups(facts: producers.Facts) -> list[dict[str, Any]]:
    """One fact group per fact that two or more items assert, such as an account's plan and a memory about it. The
    route policy's facts decide each group by producer; the assembler never compares the bodies (R-11)."""
    claims: dict[str, list[str]] = {}
    for item_id, fact in facts.items():
        claims.setdefault(fact, []).append(item_id)
    return [{"id": f"fact:{fact}", "kind": "fact", "fact": fact, "items": sorted(ids)}
            for fact, ids in sorted(claims.items()) if len(ids) >= 2]


def snapshot(conversation: Conversation, route: Route) -> dict[str, Any]:
    """Run the producers for this question and freeze what they proposed with the route's policy (snapshot.schema.json)."""
    accounts, account_facts = producers.accounts_db(conversation)
    memories, memory_facts = producers.memory_store(conversation)
    return {
        "assembly_time": conversation.asked_at,
        # Who is asking. An item that carries a scope key with another value is excluded, whoever produced it (R-2).
        "scope": {"tenant": conversation.workspace, "user": conversation.user, "session": conversation.session},
        "budget": route.budget,
        "profile": route.profile,
        "route_policy": route.policy,
        "tokenizer": route.tokenizer,
        "renderer": route.renderer,
        "batches": [
            producers.app_policy(),
            accounts,
            memories,
            producers.help_center_search(conversation.question, route.top_k),
            producers.chat_session(conversation),
        ],
        "conflicts": conflict_groups(account_facts | memory_facts),
    }


def assemble(document: dict[str, Any]) -> AssemblyResult:
    """Admission, conflict resolution, fitting and rendering: the payload to send, or none, and the trace that says why."""
    return cwa_assemble(Snapshot.from_json(document))

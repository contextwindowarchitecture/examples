"""Freeze the context of one inference into a snapshot, and assemble it.

An agent makes several inferences for one question, and each gets its own snapshot: the tools offered this turn and
the grant that names them, the account read now, the task state and observations so far, the help center, memory
and conversation, the route's policy and profile, the scope and the clock. assemble() reads nothing else and calls no
model, so every inference of a run replays to the same bytes (R-23).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cwa import AssemblyResult, Snapshot
from cwa import assemble as cwa_assemble

import producers
from conversation import Conversation
from routes import Route


@dataclass(frozen=True)
class Turn:
    """The agent's side of one inference."""
    task: str                          # the task's id: one per question
    number: int
    max_turns: int
    now: str                           # the assembly time
    steps: list[producers.Step]        # every tool call so far
    capabilities: dict[str, Any]       # the capability-policy batch for this turn
    grant: dict[str, Any]              # the snapshot's capability grant (R-15)


def conflict_groups(facts: producers.Facts) -> list[dict[str, Any]]:
    """One fact group per fact that two or more items assert, such as an account's plan and a memory about it. The
    route policy's facts decide each group by producer; the assembler never compares the bodies (R-11)."""
    claims: dict[str, list[str]] = {}
    for item_id, fact in facts.items():
        claims.setdefault(fact, []).append(item_id)
    return [{"id": f"fact:{fact}", "kind": "fact", "fact": fact, "items": sorted(ids)}
            for fact, ids in sorted(claims.items()) if len(ids) >= 2]


def snapshot(conversation: Conversation, route: Route, turn: Turn) -> dict[str, Any]:
    """Run the producers for this inference and freeze what they proposed with the route's policy."""
    accounts, account_facts = producers.accounts_db(conversation, turn.now)
    memories, memory_facts = producers.memory_store(conversation)
    return {
        "assembly_time": turn.now,
        # Who is asking, in which session, on which task. An item scoped to anything else is excluded (R-2).
        "scope": {"tenant": conversation.workspace, "user": conversation.user, "session": conversation.session,
                  "task": turn.task},
        "budget": route.budget,
        "profile": route.profile,
        "route_policy": route.policy,
        "tokenizer": route.tokenizer,
        "renderer": route.renderer,
        "batches": [
            producers.app_policy(),
            turn.capabilities,
            accounts,
            producers.agent_controller(conversation, turn.task, turn.steps, turn.number, turn.max_turns, turn.now),
            memories,
            producers.help_center_search(conversation.question, route.top_k),
            producers.fernway_api(conversation, turn.task, turn.steps),
            producers.chat_session(conversation),
        ],
        "capabilities": turn.grant,
        "conflicts": conflict_groups(account_facts | memory_facts),
    }


def assemble(document: dict[str, Any]) -> AssemblyResult:
    """Admission, conflict resolution, supersession, fitting and rendering: the payload to send, or none, and the
    trace that says why."""
    return cwa_assemble(Snapshot.from_json(document))

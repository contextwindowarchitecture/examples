"""The route's five producers. Each returns one producer batch (producer_batch.schema.json): the items it proposes for
the context window, and any it dropped itself. A batch's producer id is the identity the application vouches for, and
the route policy says which slots each one may fill (R-15).

    app-policy          governance.instructions   policy/instructions.md
    accounts-db         state.user                the workspace's plan and the user's role, read at request time
    memory-store        interaction.memory        the user's saved memories; expired and revoked ones reported, not sent
    help-center-search  evidence.knowledge        one scored item per retrieved chunk, never a merged blob (R-13),
                                                  with its summary as a variant
    chat-session        interaction.history       every prior turn, with its summary as a variant; the route decides
                                                  how many fit, and in what form
                        interaction.query         the question being asked now

A producer proposes; it never decides what fits. Thresholds, caps and the budget belong to the route policy, so every
item the assembler leaves out is a row in the trace with its reason.

A variant is a shorter body the assembler may choose instead of the original when the route's budget is tight. Every
variant here is a summary written ahead of time (summarize.py); assembly selects among them and never writes one (R-18).

accounts-db and memory-store also say which fact an item asserts, such as the workspace's plan. The application uses
that to declare conflict groups (context.py); the assembler never reads prose to find contradictions (R-11).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import corpus
from conversation import Conversation

POLICY = Path(__file__).parent / "policy"
DATA = Path(__file__).parent / "data"

# Item id -> the fact key it asserts, a key of the route policy's facts.
Facts = dict[str, str]


def item(**fields: Any) -> dict[str, Any]:
    """A context item with its policy fields declared rather than defaulted, so the trace's defaults_filled stays
    empty and every field the assembler acts on is one a producer chose (R-3)."""
    return {"token_budget": None, "variants": [], "conflict_policy": "defers", "eligibility": "route-policy", **fields}


def batch(producer_id: str, kind: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"producer": {"id": producer_id, "kind": kind}, "items": items, "excluded": []}


def app_policy() -> dict[str, Any]:
    """The application's instructions, written and versioned by the team that owns the route."""
    meta, body = corpus.front_matter((POLICY / "instructions.md").read_text(encoding="utf-8"))
    return batch("app-policy", "policy", [item(
        id="policy:instructions", slot="governance.instructions", source="app:policy/instructions.md",
        source_version=meta["version"], authority="governing", trust="verified", freshness=meta["updated"],
        conflict_policy="governs", lineage="verbatim", injection_risk="none", body=body,
    )])


def _load(name: str) -> Any:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def accounts_db(conversation: Conversation) -> tuple[dict[str, Any], Facts]:
    """The signed-in user's workspace and membership, read when the question is asked. Account state is current by
    construction (R-8): the route admits it for 300 seconds, and the application, not the model, writes it."""
    accounts = _load("accounts.json")
    workspace, member = accounts["workspaces"][conversation.workspace], accounts["users"][conversation.user]
    common = dict(slot="state.user", authority="state", trust="verified", freshness=conversation.asked_at,
                  conflict_policy="governs", lineage="extracted", injection_risk="none")
    plan_id = f"account:{conversation.workspace}:plan"
    items = [
        item(id=plan_id, source=f"accounts-db:workspaces/{conversation.workspace}", source_version=str(workspace["version"]),
             scope={"tenant": conversation.workspace},
             body=f"Workspace {workspace['name']} is on the {workspace['plan']} plan, billed {workspace['billing']}, since "
                  f"{workspace['plan_since']}. {workspace['seats']} seats. Data region: {workspace['region']}.",
             **common),
        item(id=f"account:{conversation.workspace}:{conversation.user}", source=f"accounts-db:users/{conversation.user}",
             source_version=str(member["version"]), scope={"tenant": conversation.workspace, "user": conversation.user},
             body=f"{member['name']} is a workspace {member['role']}"
                  + (" and a billing admin." if member["billing_admin"] else ", not a billing admin."),
             **common),
    ]
    return batch("accounts-db", "state", items), {plan_id: "plan"}


def memory_store(conversation: Conversation) -> tuple[dict[str, Any], Facts]:
    """The user's memories. Expired and revoked memories are never sent: the producer drops them and reports each by
    id, without its text (R-9, R-14). Scope is declared on every memory, so if the store's query is ever wrong, the
    assembler still refuses another user's memory (R-2)."""
    ignores_user = "memory-store-ignores-user" in conversation.faults  # the fault scenario 03 injects
    asked = _instant(conversation.asked_at)
    items, excluded, facts = [], [], {}
    for memory in _load("memories.json")["memories"]:
        if memory["workspace"] != conversation.workspace or (memory["user"] != conversation.user and not ignores_user):
            continue
        if "revoked_by" in memory:
            excluded.append({"item_id": memory["id"], "reason": "revoked", "stage": "producer"})
            continue
        if _instant(memory["expires"]) <= asked:
            excluded.append({"item_id": memory["id"], "reason": "expired", "stage": "producer"})
            continue
        items.append(item(
            id=memory["id"], slot="interaction.memory", source=memory["from_turn"], source_version="1",
            authority="generated", trust="unverified", freshness=memory["saved_at"], expires=memory["expires"],
            scope={"tenant": memory["workspace"], "user": memory["user"]}, lineage="summarised",
            injection_risk="untrusted_content", body=memory["text"],
        ))
        if "fact" in memory:
            facts[memory["id"]] = memory["fact"]
    return {"producer": {"id": "memory-store", "kind": "memory"}, "items": items, "excluded": excluded}, facts


def summary_variant(item_id: str, summary: dict[str, str] | None) -> list[dict[str, str]]:
    """A summary as a variant: its own id and method, and lineage summarised. It inherits its parent's provenance,
    scope and authority (R-18)."""
    if summary is None:
        return []
    return [{"id": f"{item_id}~summary", "method": summary["method"], "lineage": "summarised", "body": summary["text"]}]


def help_center_search(question: str, top_k: int) -> dict[str, Any]:
    """Every retrieved chunk, with its BM25 score as relevance and its summary, if it has a current one. The producer
    does not filter by score: the route's min_relevance does, so the trace shows which chunks fell short and by how
    much (R-13)."""
    items = []
    for hit in corpus.retrieve(question, top_k):
        meta = hit.node.metadata
        items.append(item(
            id=hit.node.node_id, slot="evidence.knowledge", source=f"help-center:{meta['article']}",
            source_version=meta["version"], authority="reference_only", trust="verified", freshness=meta["updated"],
            relevance=round(hit.score or 0.0, 3), lineage="verbatim",
            # The help center is ours, but retrieved text is still data, never instructions (R-10).
            injection_risk="untrusted_content", body=hit.node.get_content(),
            variants=summary_variant(hit.node.node_id, corpus.summary(hit.node)),
        ))
    return batch("help-center-search", "retrieval", items)


def turn_id(session: str, n: int) -> str:
    # Zero-padded, so ordering by id, as the renderer does, is the conversation's order.
    return f"turn:{session}:{n:04d}"


def chat_session(conversation: Conversation) -> dict[str, Any]:
    """Every prior turn of this session, and the question. Nothing is trimmed here: how much history fits is the
    route's decision (interaction.history max_tokens), and the trace records each turn it leaves out (R-16)."""
    scope = {"session": conversation.session}
    source = f"chat:{conversation.session}"
    items = []
    for n, turn in enumerate(conversation.turns, start=1):
        generated = turn.role == "assistant"
        items.append(item(
            id=turn_id(conversation.session, n), slot="interaction.history", source=source, source_version="1",
            # The model's earlier answers carry no authority (R-1). They render as a transcript marked as the
            # assistant's, never as messages of their own (R-7).
            authority="untrusted" if generated else "user", lineage="generated" if generated else "verbatim",
            trust="unverified", freshness=turn.at, scope=scope, injection_risk="untrusted_content", body=turn.text,
            variants=summary_variant(turn_id(conversation.session, n), turn.summary),
        ))
    items.append(item(
        id=turn_id(conversation.session, len(conversation.turns) + 1), slot="interaction.query", source=source,
        source_version="1", authority="user", lineage="verbatim", trust="unverified", freshness=conversation.asked_at,
        scope=scope, injection_risk="untrusted_content", body=conversation.question,
    ))
    return batch("chat-session", "interaction", items)

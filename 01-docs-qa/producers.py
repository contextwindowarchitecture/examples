"""The route's three producers. Each returns one producer batch (producer_batch.schema.json): the items it proposes for
the context window, and any it dropped itself. A batch's producer id is the identity the application vouches for, and
the route policy says which slots each one may fill (R-15).

    app-policy          governance.instructions   policy/instructions.md
    help-center-search  evidence.knowledge        one scored item per retrieved chunk, never a merged blob (R-13)
    chat-session        interaction.history       every prior turn; the route decides how many fit
                        interaction.query         the question being asked now

A producer proposes; it never decides what fits. Thresholds, caps and the budget belong to the route policy, so every
item the assembler leaves out is a row in the trace with its reason.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import corpus
from conversation import Conversation

POLICY = Path(__file__).parent / "policy"


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


def help_center_search(question: str, top_k: int) -> dict[str, Any]:
    """Every retrieved chunk, with its BM25 score as relevance. The producer does not filter by score: the route's
    min_relevance does, so the trace shows which chunks fell short and by how much (R-13)."""
    items = []
    for hit in corpus.retrieve(question, top_k):
        meta = hit.node.metadata
        items.append(item(
            id=hit.node.node_id, slot="evidence.knowledge", source=f"help-center:{meta['article']}",
            source_version=meta["version"], authority="reference_only", trust="verified", freshness=meta["updated"],
            relevance=round(hit.score or 0.0, 3), lineage="verbatim",
            # The help center is ours, but retrieved text is still data, never instructions (R-10).
            injection_risk="untrusted_content", body=hit.node.get_content(),
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
        ))
    items.append(item(
        id=turn_id(conversation.session, len(conversation.turns) + 1), slot="interaction.query", source=source,
        source_version="1", authority="user", lineage="verbatim", trust="unverified", freshness=conversation.asked_at,
        scope=scope, injection_risk="untrusted_content", body=conversation.question,
    ))
    return batch("chat-session", "interaction", items)

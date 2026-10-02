"""What this example claims CWA gives the help-center bot, each claim stated as a test on a committed scenario."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from cwa import AssemblyResult

import after
import context
import providers
import scenarios
from conversation import Conversation


def conversation(name: str) -> Conversation:
    return Conversation.load(scenarios.SCENARIOS / name / "conversation.json")


def run(name: str) -> tuple[dict[str, Any], AssemblyResult]:
    document = context.snapshot(conversation(name))
    return document, context.assemble(document)


def candidates(document: dict[str, Any], slot: str | None = None) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for batch in document["batches"] for item in batch["items"] if slot in (None, item["slot"])}


@pytest.mark.parametrize("name", ["01-answer", "02-long-conversation"])
def test_every_candidate_is_either_sent_or_left_out_with_a_reason(name: str) -> None:
    # A refused trace includes nothing (R-17), so this holds for assemblies that produced a request.
    document, result = run(name)
    sent = {row["item_id"] for row in result.trace["included"]}
    left_out = {row["item_id"] for row in result.trace["excluded"]}
    assert sent | left_out == set(candidates(document))
    assert not sent & left_out
    assert all(row["reason"] for row in result.trace["excluded"])


def test_chunks_scoring_below_the_route_threshold_are_left_out_and_say_so() -> None:
    document, result = run("01-answer")
    threshold = document["route_policy"]["slots"]["evidence.knowledge"]["min_relevance"]
    chunks = candidates(document, "evidence.knowledge")
    sent = [row["item_id"] for row in result.trace["included"] if row["slot"] == "evidence.knowledge"]
    below = [row["item_id"] for row in result.trace["excluded"] if row["reason"] == "below_threshold"]
    assert sent and all(chunks[chunk]["relevance"] >= threshold for chunk in sent)
    assert below and all(chunks[chunk]["relevance"] < threshold for chunk in below)


@pytest.mark.parametrize("name", ["01-answer", "02-long-conversation"])
def test_the_instructions_and_the_question_are_always_sent(name: str) -> None:
    document, result = run(name)
    sent = {row["slot"] for row in result.trace["included"]}
    assert {"governance.instructions", "interaction.query"} <= sent


def test_a_long_conversation_keeps_its_newest_turns_within_the_history_cap() -> None:
    document, result = run("02-long-conversation")
    cap = document["route_policy"]["slots"]["interaction.history"]["max_tokens"]
    kept = [row for row in result.trace["included"] if row["slot"] == "interaction.history"]
    dropped = [row["item_id"] for row in result.trace["excluded"] if row["reason"] == "over_budget"]
    assert kept and dropped, "the conversation is longer than the cap, so some turns are dropped and some kept"
    assert sum(row["tokens"] for row in kept) <= cap
    # Turn ids are zero-padded, so string order is turn order: every dropped turn is older than every kept one.
    assert max(dropped) < min(row["item_id"] for row in kept)


def test_an_off_topic_question_is_refused_and_never_reaches_a_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def no_model(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("a refused assembly reached a model")

    monkeypatch.setattr(providers, "ask", no_model)
    assert after.answer(conversation("03-off-topic"), "anthropic", None, out=io.StringIO(), runs=tmp_path) is None
    _, result = run("03-off-topic")
    assert result.payload is None
    assert result.trace["refused"] == {"bool": True, "reason": "evidence_required"}
    assert result.trace["recovery"]["action"] == "request_context"


def test_a_saved_run_replays_to_the_same_request(tmp_path: Path) -> None:
    after.answer(conversation("01-answer"), "none", None, out=io.StringIO(), runs=tmp_path)
    [saved] = list(tmp_path.iterdir())
    assert (saved / "payload.json").exists()
    assert after.replay(saved / "snapshot.json", out=io.StringIO())

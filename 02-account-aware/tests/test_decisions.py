"""What this example claims account state and memory add, each claim stated as a test on a committed scenario."""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from cwa import AssemblyResult

import app
import context
import scenarios
from conversation import Conversation


def conversation(name: str) -> Conversation:
    return Conversation.load(scenarios.SCENARIOS / name / "conversation.json")


def run(name: str) -> tuple[dict[str, Any], AssemblyResult]:
    document = context.snapshot(conversation(name))
    return document, context.assemble(document)


def sent(result: AssemblyResult, slot: str) -> list[str]:
    return [row["item_id"] for row in result.trace["included"] if row["slot"] == slot]


def left_out(result: AssemblyResult, reason: str) -> list[str]:
    return [row["item_id"] for row in result.trace["excluded"] if row["reason"] == reason]


def message(result: AssemblyResult) -> str:
    assert result.payload is not None
    return json.loads(result.payload)["messages"][0]["content"]


@pytest.mark.parametrize("name", scenarios.names())
def test_every_candidate_is_either_sent_or_left_out_with_a_reason(name: str) -> None:
    document, result = run(name)
    candidates = {item["id"] for batch in document["batches"] for item in batch["items"]}
    included = {row["item_id"] for row in result.trace["included"]}
    excluded = {row["item_id"] for row in result.trace["excluded"] if row["stage"] == "assembler"}
    assert included | excluded == candidates
    assert not included & excluded


@pytest.mark.parametrize("name", scenarios.names())
def test_the_account_is_sent_for_the_signed_in_user(name: str) -> None:
    document, result = run(name)
    workspace, user = document["scope"]["tenant"], document["scope"]["user"]
    assert sent(result, "state.user") == [f"account:{workspace}:plan", f"account:{workspace}:{user}"]


def test_expired_and_revoked_memories_are_reported_by_the_producer_without_their_text() -> None:
    document, result = run("01-team-plan")
    reported = {row["item_id"]: row["reason"] for row in result.trace["excluded"] if row["stage"] == "producer"}
    assert reported == {"mem:u_cho:0002": "expired", "mem:u_cho:0004": "revoked"}
    candidates = {item["id"] for batch in document["batches"] for item in batch["items"]}
    assert not candidates & set(reported), "a suppressed memory's text never enters the snapshot (R-14)"
    assert "30-day trial" not in message(result) and "approve every plan change" not in message(result)


def test_a_memory_that_disagrees_with_the_account_loses_by_policy() -> None:
    _, result = run("02-memory-disagrees")
    [group] = result.trace["conflicts"]
    assert group["group_id"] == "fact:plan"
    assert (group["decided_by"], group["winner"]) == ("policy", "account:w_kitewood:plan")
    assert left_out(result, "conflict_lost") == ["mem:u_ada:0003"]
    assert "Their workspace is on the Team plan." not in message(result)
    assert "Kitewood Studio is on the Business plan" in message(result)


def test_another_users_memories_are_kept_out_even_when_the_memory_store_returns_them() -> None:
    document, result = run("03-memory-leak")
    memories = {item["id"] for batch in document["batches"] for item in batch["items"] if item["slot"] == "interaction.memory"}
    assert {"mem:u_ada:0003", "mem:u_ada:0005"} <= memories, "the injected fault does reach the snapshot"
    assert sorted(left_out(result, "out_of_scope")) == ["mem:u_ada:0003", "mem:u_ada:0005"]
    assert sent(result, "interaction.memory") == ["mem:u_ben:0001"]
    assert "Okta" not in message(result)


def test_without_the_fault_the_memory_store_returns_only_the_users_memories() -> None:
    faultless = conversation("03-memory-leak")
    faultless.faults = []
    document = context.snapshot(faultless)
    memories = [item["id"] for batch in document["batches"] for item in batch["items"] if item["slot"] == "interaction.memory"]
    assert memories == ["mem:u_ben:0001"]


def test_a_saved_run_replays_to_the_same_request(tmp_path: Path) -> None:
    app.answer(conversation("02-memory-disagrees"), "none", None, out=io.StringIO(), runs=tmp_path)
    [saved] = list(tmp_path.iterdir())
    assert app.replay(saved / "snapshot.json", out=io.StringIO())

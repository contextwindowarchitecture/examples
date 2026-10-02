"""What this example claims summaries and routes add, each claim stated as a test on a committed scenario."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from cwa import AssemblyResult
from llama_index.core.schema import TextNode

import app
import context
import corpus
import providers
import routes
import scenarios
from conversation import Conversation

PROTECTED = ("governance.instructions", "state.user", "interaction.query")


def conversation(name: str) -> Conversation:
    return Conversation.load(scenarios.SCENARIOS / name / "conversation.json")


def run(name: str) -> tuple[dict[str, Any], AssemblyResult]:
    chat = conversation(name)
    document = context.snapshot(chat, routes.load(chat.route or routes.default()))
    return document, context.assemble(document)


def rows(result: AssemblyResult, slot: str) -> dict[str, int]:
    return {row["item_id"]: row["tokens"] for row in result.trace["included"] if row["slot"] == slot}


@pytest.mark.parametrize("name", ["01-large-route", "02-small-route", "04-pasted-log-escalated"])
def test_every_candidate_is_either_sent_or_left_out_with_a_reason(name: str) -> None:
    document, result = run(name)
    candidates = {item["id"] for batch in document["batches"] for item in batch["items"]}
    included = {row["item_id"] for row in result.trace["included"]}
    excluded = {row["item_id"] for row in result.trace["excluded"] if row["stage"] == "assembler"}
    assert included | excluded == candidates
    assert not included & excluded


def test_the_large_route_sends_the_conversation_whole() -> None:
    _, result = run("01-large-route")
    assert result.trace["compressed"] == []
    assert not [row for row in result.trace["excluded"] if row["reason"] == "over_budget"]


def test_the_small_route_sends_summaries_instead_of_long_bodies() -> None:
    document, result = run("02-small-route")
    variants = {variant["id"]: item["id"] for batch in document["batches"] for item in batch["items"]
                for variant in item["variants"]}
    assert result.trace["compressed"], "the small route's budget needs summaries"
    for row in result.trace["compressed"]:
        assert variants[row["variant_id"]] == row["item_id"]
        assert row["to"] < row["from"]


def test_the_small_route_keeps_history_within_its_cap() -> None:
    document, result = run("02-small-route")
    cap = document["route_policy"]["slots"]["interaction.history"]["max_tokens"]
    assert sum(rows(result, "interaction.history").values()) <= cap


def test_protected_items_are_sent_whole_on_both_routes() -> None:
    _, large = run("01-large-route")
    _, small = run("02-small-route")
    compressed = {row["item_id"] for row in small.trace["compressed"]}
    for slot in PROTECTED:
        assert rows(small, slot) == rows(large, slot)
        assert not compressed & set(rows(small, slot))


def test_the_same_conversation_makes_a_different_request_on_each_route() -> None:
    _, large = run("01-large-route")
    _, small = run("02-small-route")
    assert large.payload != small.payload
    assert (large.trace["profile"]["id"], small.trace["profile"]["id"]) == ("account-help-messages", "account-help-small-messages")
    assert large.trace["context"]["route_policy_version"] == "account-help/v2"
    assert small.trace["context"]["route_policy_version"] == "account-help-small/v1"


def test_a_pasted_log_too_big_for_the_small_route_is_refused_whole() -> None:
    _, result = run("03-pasted-log")
    assert result.payload is None
    assert result.trace["refused"] == {"bool": True, "reason": "protected_content_over_budget"}


def test_the_same_pasted_log_fits_the_large_route() -> None:
    _, result = run("04-pasted-log-escalated")
    assert result.payload is not None
    assert "interaction.query" in {row["slot"] for row in result.trace["included"]}


def test_the_app_escalates_to_the_large_route_and_asks_its_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    asked: list[dict[str, Any]] = []

    def model(provider: str, options: dict[str, Any], *args: Any) -> str:
        asked.append(options)
        return "answer"

    monkeypatch.setattr(providers, "ask", model)
    chat = conversation("03-pasted-log")
    chat.route = None  # let the application choose: the small route first
    assert app.answer(chat, "anthropic", None, out=io.StringIO(), runs=tmp_path) == "answer"
    outcomes = sorted((path / "payload.json").exists() for path in tmp_path.iterdir())
    assert outcomes == [False, True], "one refused snapshot on the small route, then one assembled on the large route"
    assert [options["model"] for options in asked] == [routes.load("account-help").models["anthropic"]["model"]]


@pytest.mark.parametrize("name", ["02-small-route", "03-pasted-log"])
def test_a_model_on_the_command_line_replaces_the_routes_settings(name: str, monkeypatch: pytest.MonkeyPatch,
                                                                  tmp_path: Path) -> None:
    # --model is that model on the endpoint the environment names, as in 04 and 05, whichever route answers. The small
    # route's reasoning effort and the large route's own endpoint and key variable belong to the route's model.
    asked: list[dict[str, Any]] = []

    def model(provider: str, options: dict[str, Any], *args: Any) -> str:
        asked.append(options)
        return "answer"

    monkeypatch.setattr(providers, "ask", model)
    chat = conversation(name)
    chat.route = None  # the small route first; the pasted log escalates to the large one
    assert app.answer(chat, "openai", "vendor/some-model", out=io.StringIO(), runs=tmp_path) == "answer"
    assert asked == [{"model": "vendor/some-model"}]


def test_a_summary_is_offered_only_for_the_text_it_was_made_from() -> None:
    node = corpus.nodes()[0]
    assert corpus.summary(node) is not None
    edited = TextNode(id_=node.node_id, text=node.get_content() + " Edited.")
    assert corpus.summary(edited) is None


def test_a_saved_run_replays_to_the_same_request(tmp_path: Path) -> None:
    app.answer(conversation("02-small-route"), "none", None, out=io.StringIO(), runs=tmp_path)
    [saved] = list(tmp_path.iterdir())
    assert app.replay(saved / "snapshot.json", out=io.StringIO())

"""What --record keeps of one question: the conversation, what was sent, and the reply, so a run can be read or
compared later without the console output."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import after
import before
import providers
import scenarios
from conversation import Conversation


def scenario(name: str) -> Path:
    return scenarios.SCENARIOS / name


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def test_after_records_the_conversation_the_assembly_and_the_reply(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(providers, "ask", lambda *args: "the answer")
    record = tmp_path / "record"
    argv = ["--conversation", str(scenario("01-answer") / "conversation.json"), "--provider", "openai", "--model", "m",
            "--record", str(record)]
    assert after.main(argv, runs=tmp_path / "runs") == 0
    assert Conversation.load(record / "conversation.json") == Conversation.load(scenario("01-answer") / "conversation.json")
    for name in ("snapshot.json", "payload.json"):
        assert (record / name).read_bytes() == (scenario("01-answer") / name).read_bytes()
    assert read(record / "trace.json")["result"] == read(scenario("01-answer") / "trace.json")["result"]
    assert read(record / "run.json") == {"provider": "openai", "model": "m", "answer": "the answer", "error": None}


def test_a_refused_question_is_recorded_without_a_payload_or_a_reply(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def no_model(*args: Any) -> str:
        raise AssertionError("a refused assembly reached a model")

    monkeypatch.setattr(providers, "ask", no_model)
    record = tmp_path / "record"
    argv = ["--conversation", str(scenario("03-off-topic") / "conversation.json"), "--provider", "openai", "--model", "m",
            "--record", str(record)]
    assert after.main(argv, runs=tmp_path / "runs") == 0
    assert sorted(path.name for path in record.iterdir()) == ["conversation.json", "run.json", "snapshot.json", "trace.json"]
    assert read(record / "run.json")["answer"] is None


def test_before_records_the_request_it_built(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sent: list[dict[str, Any]] = []

    def model(provider: str, name: str, system: list[str], messages: list[dict[str, str]], max_tokens: int) -> str:
        sent.append({"system": system, "messages": messages})
        return "the answer"

    monkeypatch.setattr(providers, "ask", model)
    argv = ["--conversation", str(scenario("01-answer") / "conversation.json"), "--provider", "openai", "--model", "m",
            "--record", str(tmp_path)]
    assert before.main(argv) == 0
    # Nothing recorded what before.py left out, so there is no snapshot or trace to keep: only the request.
    assert sorted(path.name for path in tmp_path.iterdir()) == ["conversation.json", "request.json", "run.json"]
    assert [read(tmp_path / "request.json")] == sent


def test_a_provider_error_is_recorded_in_place_of_the_reply(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def failing(*args: Any) -> str:
        raise providers.ProviderError("rate limited")

    monkeypatch.setattr(providers, "ask", failing)
    argv = ["--conversation", str(scenario("01-answer") / "conversation.json"), "--provider", "openai", "--model", "m",
            "--record", str(tmp_path / "record")]
    assert after.main(argv, runs=tmp_path / "runs") == 1
    assert read(tmp_path / "record" / "run.json") == {"provider": "openai", "model": "m", "answer": None,
                                                       "error": "rate limited"}


def test_record_needs_one_question(tmp_path: Path) -> None:
    assert after.main(["--provider", "openai", "--record", str(tmp_path)], runs=tmp_path / "runs") == 2

"""What --record keeps of one question: the conversation, each route's assembly, and the reply, so a run can be read
or compared later without the console output."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import app
import providers
import scenarios
from conversation import Conversation


def scenario(name: str) -> Path:
    return scenarios.SCENARIOS / name


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_app_records_the_conversation_the_routes_assembly_and_the_reply(monkeypatch: pytest.MonkeyPatch,
                                                                             tmp_path: Path) -> None:
    monkeypatch.setattr(providers, "ask", lambda *args: "the answer")
    record = tmp_path / "record"
    committed = scenario("02-small-route")
    argv = ["--conversation", str(committed / "conversation.json"), "--provider", "openai", "--model", "m",
            "--record", str(record)]
    assert app.main(argv, runs=tmp_path / "runs") == 0
    assert Conversation.load(record / "conversation.json") == Conversation.load(committed / "conversation.json")
    assert sorted(path.name for path in record.iterdir()) == ["account-help-small", "conversation.json", "run.json"]
    for name in ("snapshot.json", "payload.json"):
        assert (record / "account-help-small" / name).read_bytes() == (committed / name).read_bytes()
    assert read(record / "account-help-small" / "trace.json")["compressed"] == read(committed / "trace.json")["compressed"]
    assert read(record / "run.json") == {"provider": "openai", "model": "m", "answer": "the answer", "error": None}


def test_an_escalation_records_the_refused_route_and_the_route_that_answered(monkeypatch: pytest.MonkeyPatch,
                                                                              tmp_path: Path) -> None:
    monkeypatch.setattr(providers, "ask", lambda *args: "the answer")
    record = tmp_path / "record"
    argv = ["--conversation", str(scenario("03-pasted-log") / "conversation.json"), "--provider", "openai", "--model", "m",
            "--record", str(record)]
    assert app.main(argv, runs=tmp_path / "runs") == 0
    # The small route refused, so it has no payload. The large route froze a new snapshot: the committed scenario 04.
    assert sorted(path.name for path in (record / "account-help-small").iterdir()) == ["snapshot.json", "trace.json"]
    assert read(record / "account-help-small" / "trace.json")["refused"]["reason"] == "protected_content_over_budget"
    for name in ("snapshot.json", "payload.json"):
        assert (record / "account-help" / name).read_bytes() == (scenario("04-pasted-log-escalated") / name).read_bytes()
    assert read(record / "run.json")["answer"] == "the answer"


def test_a_provider_error_is_recorded_in_place_of_the_reply(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def failing(*args: Any) -> str:
        raise providers.ProviderError("rate limited")

    monkeypatch.setattr(providers, "ask", failing)
    argv = ["--conversation", str(scenario("01-large-route") / "conversation.json"), "--provider", "openai",
            "--model", "m", "--record", str(tmp_path / "record")]
    assert app.main(argv, runs=tmp_path / "runs") == 1
    assert read(tmp_path / "record" / "run.json") == {"provider": "openai", "model": "m", "answer": None,
                                                       "error": "rate limited"}


def test_record_needs_one_question(tmp_path: Path) -> None:
    assert app.main(["--provider", "openai", "--record", str(tmp_path)], runs=tmp_path / "runs") == 2

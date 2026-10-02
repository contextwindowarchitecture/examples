"""The committed scenarios are what the code builds now, and a stored snapshot replays to the stored request.

The first test is the context regression check: edit an article, the instructions or the route policy, and it fails
until `uv run scenarios.py --write` regenerates the scenarios and the diff is committed for review. The second needs
no producers at all: the committed snapshot alone assembles to the committed payload, byte for byte (R-23).
"""
from __future__ import annotations

import json

import pytest

import context
import scenarios


@pytest.mark.parametrize("name", scenarios.names())
def test_the_committed_scenario_is_what_the_code_builds_now(name: str) -> None:
    assert scenarios.stale(name) == [], "run `uv run scenarios.py --write`, then review the diff"


@pytest.mark.parametrize("name", scenarios.names())
def test_the_committed_snapshot_replays_to_the_committed_request(name: str) -> None:
    directory = scenarios.SCENARIOS / name
    result = context.assemble(json.loads((directory / "snapshot.json").read_text(encoding="utf-8")))
    payload = directory / "payload.json"
    assert result.payload == (payload.read_bytes() if payload.exists() else None)
    trace = json.loads((directory / "trace.json").read_text(encoding="utf-8"))
    assert result.trace["result"] == trace["result"]
    assert result.trace["refused"] == trace["refused"]
    assert result.trace["context"]["snapshot_digest"] == trace["context"]["snapshot_digest"]


def test_there_are_scenarios_to_check() -> None:
    assert scenarios.names() == ["01-answer", "02-long-conversation", "03-off-topic"]

"""The committed agent runs are what a replay builds now, and every inference's snapshot replays to its request.

The first test replays each scenario through the real loop, capability policy, guard, MCP server and assembler, with
only the model and the clock played back, and compares every file. The second needs no loop: each committed
snapshot alone assembles to the committed payload, byte for byte (R-23).
"""
from __future__ import annotations

import json

import pytest

import context
import scenarios


@pytest.mark.parametrize("name", scenarios.names())
def test_the_committed_run_is_what_a_replay_builds_now(name: str) -> None:
    assert scenarios.stale(name) == [], "run `uv run scenarios.py --write`, then review the diff"


@pytest.mark.parametrize("name", scenarios.names())
def test_every_committed_snapshot_replays_to_its_request(name: str) -> None:
    turns = sorted((scenarios.SCENARIOS / name).glob("turn-*"))
    assert turns
    for turn in turns:
        result = context.assemble(json.loads((turn / "snapshot.json").read_text(encoding="utf-8")))
        payload = turn / "payload.json"
        assert result.payload == (payload.read_bytes() if payload.exists() else None), turn.name
        trace = json.loads((turn / "trace.json").read_text(encoding="utf-8"))
        assert result.trace["context"]["snapshot_digest"] == trace["context"]["snapshot_digest"]


def test_there_are_scenarios_to_check() -> None:
    assert scenarios.names() == ["01-owner-reenables", "02-member-reads-only", "03-injected-instruction"]

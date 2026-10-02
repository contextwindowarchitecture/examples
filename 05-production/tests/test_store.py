"""The snapshot store keeps every inference once, replays it to the same bytes, and re-decides it under a candidate
policy before that policy ships."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import store
from conftest import RESULTS, replay

FOLDER = RESULTS[0] / "owner-reenables"
CANDIDATE = Path(__file__).parent.parent / "policy" / "candidates" / "stricter-relevance"
CURRENT = Path(__file__).parent.parent / "policy" / "account-agent"


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    connection = store.connect(tmp_path / "cwa.sqlite")
    store.save(connection, "run-1", "2026-10-02T09:00:00Z", "w_kitewood", "u_ada", "question", "scripted", replay(FOLDER))
    return connection


def count(db: sqlite3.Connection, table: str) -> int:
    return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_a_run_is_stored_with_every_inference_and_tool_call(db: sqlite3.Connection) -> None:
    recorded = json.loads((FOLDER / "run.json").read_text(encoding="utf-8"))
    turns = len(list(FOLDER.glob("turn-*")))
    assert count(db, "inferences") == turns
    assert count(db, "steps") == len(recorded["steps"])
    assert db.execute("SELECT answer FROM runs").fetchone()[0] == recorded["answer"]


def test_a_snapshot_is_stored_once_however_often_it_is_used(db: sqlite3.Connection) -> None:
    before = count(db, "snapshots")
    store.save(db, "run-2", "2026-10-02T09:05:00Z", "w_kitewood", "u_ada", "question", "scripted", replay(FOLDER))
    assert count(db, "snapshots") == before
    assert count(db, "inferences") == 2 * before


def test_a_stored_run_replays_to_the_same_bytes(db: sqlite3.Connection) -> None:
    replayed = store.replay(db, "run-1")
    assert replayed and all(item.same for item in replayed)


def test_the_current_policy_changes_nothing(db: sqlite3.Connection) -> None:
    policy = json.loads((CURRENT / "route-policy.json").read_text(encoding="utf-8"))
    profile = json.loads((CURRENT / "profile.json").read_text(encoding="utf-8"))
    assert store.whatif(db, policy, profile) == []


def test_a_candidate_policy_shows_what_it_would_change(db: sqlite3.Connection) -> None:
    policy = json.loads((CANDIDATE / "route-policy.json").read_text(encoding="utf-8"))
    profile = json.loads((CANDIDATE / "profile.json").read_text(encoding="utf-8"))
    differences = store.whatif(db, policy, profile)
    changes = [change for difference in differences for change in difference.changes]
    assert "help:webhooks@2#0: sent -> below_threshold" in changes
    assert any(change.startswith("input tokens:") for change in changes)


@pytest.mark.parametrize("folder", sorted(path for results in RESULTS for path in results.iterdir() if path.is_dir()),
                         ids=lambda path: f"{path.parent.name}/{path.name}")
def test_every_recorded_snapshot_replays_to_its_recorded_request(folder: Path) -> None:
    import context
    for turn in sorted(folder.glob("turn-*")):
        result = context.assemble(json.loads((turn / "snapshot.json").read_text(encoding="utf-8")))
        payload = turn / "payload.json"
        assert result.payload == (payload.read_bytes() if payload.exists() else None), f"{folder.name}/{turn.name}"

"""Grading a run from its files: the replay, in an example's environment, and each job's checks.json."""
from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import grade
from config import ROOT
from test_checks import as_the_openai_provider_sends
from test_summary import run_with


def recorded(tmp_path: Path, *scenarios: str) -> list[Path]:
    """Committed 01 scenarios, copied as a run would record them."""
    paths = []
    for scenario in scenarios:
        folder = tmp_path / scenario
        shutil.copytree(ROOT / "01-docs-qa" / "scenarios" / scenario, folder)
        paths.append(folder / "snapshot.json")
    return paths


def test_every_recorded_snapshot_assembles_again_to_its_payload_and_outcome(tmp_path: Path) -> None:
    answer, off_topic = recorded(tmp_path, "01-answer", "03-off-topic")
    assert grade.replay([answer, off_topic]) == {str(answer): {"payload": True, "outcome": True},
                                                 str(off_topic): {"payload": True, "outcome": True}}
    tampered = answer.with_name("payload.json")
    tampered.write_bytes(tampered.read_bytes().replace(b"spam", b"SPAM"))
    assert grade.replay([answer])[str(answer)] == {"payload": False, "outcome": True}


def test_every_job_gets_its_checks_and_the_run_a_table_by_model(tmp_path: Path) -> None:
    run = tmp_path / "run"
    job = run / "vendor-model" / "01-docs-qa" / "01-answer" / "after" / "1"
    shutil.copytree(ROOT / "01-docs-qa" / "scenarios" / "01-answer", job / "record")
    (job / "record" / "run.json").write_text(json.dumps({"provider": "openai", "model": "vendor/model",
                                                          "answer": "Check spam [help:sign-in@6#0].", "error": None}))
    (job / "job.json").write_text(json.dumps({"model": "vendor/model", "example": "01-docs-qa", "case": "01-answer/after",
                                              "repeat": 1, "exit": 0}))
    (job / "calls").mkdir()
    payload = json.loads((job / "record" / "payload.json").read_text())
    (job / "calls" / "1.request.json").write_text(json.dumps(as_the_openai_provider_sends(payload)))
    name = job.relative_to(run).as_posix()
    (run / "calls.jsonl").write_text(json.dumps({"job": name, "call": 1, "status": 200, "error": None}) + "\n")
    out = io.StringIO()
    graded = grade.grade(run, replayed={str(job / "record" / "snapshot.json"): {"payload": True, "outcome": True}}, out=out)
    written = json.loads((job / "checks.json").read_text())
    assert written["job"] == name and all(check["passed"] is not False for check in written["checks"])
    assert [check.check for check in graded[name] if check.measure == "invariant"] == ["payload_sent", "same_context", "replays"]
    table = out.getvalue()
    assert "vendor-model" in table and "invariant" in table and "3/3" in table


def test_grading_a_run_writes_its_summary_and_its_numbers(tmp_path: Path) -> None:
    run = run_with(tmp_path)
    job = run / "vendor-model" / "01-docs-qa" / "01-answer" / "after" / "1"
    payload = json.loads((job / "record" / "payload.json").read_text())
    (job / "calls").mkdir()
    (job / "calls" / "1.request.json").write_text(json.dumps(as_the_openai_provider_sends(payload)))
    grade.grade(run, replayed={str(job / "record" / "snapshot.json"): {"payload": True, "outcome": True}}, out=io.StringIO())
    numbers = json.loads((run / "numbers.json").read_text())
    assert numbers["run"] == json.loads((run / "summary.json").read_text())["run"] == run.name
    assert numbers["models"] == ["vendor/model"] and numbers["pages"]


def test_a_run_given_by_a_relative_path_replays_from_the_examples_folder(tmp_path: Path, monkeypatch) -> None:
    # The replay runs in an example's folder, so a path relative to bench/ must not reach it as it is.
    recorded(tmp_path, "01-answer")
    monkeypatch.chdir(tmp_path)
    relative = Path("01-answer") / "snapshot.json"
    assert grade.replay([relative]) == {str(relative): {"payload": True, "outcome": True}}

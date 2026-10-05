"""Running a job, and what a run records so it can be resumed. No example is spawned: subprocess.run is replaced."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import cases
import catalog
import config
import manifest
import plan
import run

CASE = cases.Case(example="01-docs-qa", name="01-answer/after", args=("after.py", "--conversation", "c.json"),
                  output="--record", tools=False, calls=1, most_calls=1, input_tokens=283,
                  budget=cases.Budget(input=1500, reserved_output=16000))
JOB = plan.Job("vendor/paid", CASE, 1)
LISTINGS = {"vendor/paid": catalog.Listing(input_price=2e-06, output_price=1e-05, tools=True)}


class Proxy:
    spent = 0.0

    def base_url(self, job: Path) -> str:
        return f"http://127.0.0.1:9/{job.as_posix()}"


def test_an_example_sees_the_proxy_and_a_dummy_key_never_the_real_one(monkeypatch: pytest.MonkeyPatch,
                                                                      tmp_path: Path) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-real")
    monkeypatch.setenv("VIRTUAL_ENV", "/bench/.venv")
    environ = run.environment("http://127.0.0.1:9/job", "OPENROUTER_API_KEY", tmp_path / "store.sqlite")
    assert "OPENROUTER_API_KEY" not in environ and "VIRTUAL_ENV" not in environ
    assert (environ["OPENAI_BASE_URL"], environ["OPENAI_API_KEY"]) == ("http://127.0.0.1:9/job", "bench-proxy")
    assert environ["DOCS_QA_STORE"] == str(tmp_path / "store.sqlite")  # 05's store/cwa.sqlite keeps only your own runs


def test_a_job_runs_the_examples_command_in_its_folder_and_says_how_it_ended(monkeypatch: pytest.MonkeyPatch,
                                                                            tmp_path: Path) -> None:
    ran: list[dict[str, Any]] = []

    def spawn(argv: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        ran.append({"argv": argv, "cwd": options["cwd"], "base_url": options["env"]["OPENAI_BASE_URL"]})
        return subprocess.CompletedProcess(argv, 1)

    monkeypatch.setattr(run.subprocess, "run", spawn)
    folder = tmp_path / JOB.folder
    (folder / "calls").mkdir(parents=True)
    (folder / "calls" / "1.request.json").write_text("{}")  # left by an earlier attempt
    assert run.execute(JOB, tmp_path, Proxy(), "OPENROUTER_API_KEY", lambda *args: None) is False
    [spawned] = ran
    assert spawned["argv"][-2:] == ["--record", str(folder / "record")]
    assert (spawned["cwd"], spawned["base_url"]) == (config.ROOT / "01-docs-qa", f"http://127.0.0.1:9/{JOB.folder.as_posix()}")
    assert not (folder / "calls").exists(), "a job runs again from an empty folder"
    ended = json.loads((folder / "job.json").read_text(encoding="utf-8"))
    assert (ended["exit"], ended["model"], ended["case"]) == (1, "vendor/paid", "01-answer/after")
    assert not run.finished(folder)


def test_a_job_is_finished_only_when_its_command_succeeded(tmp_path: Path) -> None:
    assert not run.finished(tmp_path)
    (tmp_path / "job.json").write_text(json.dumps({"exit": 0}))
    assert run.finished(tmp_path)


def test_a_resumed_run_counts_what_it_already_spent(tmp_path: Path) -> None:
    assert run.spent_before(tmp_path) == 0
    (tmp_path / "calls.jsonl").write_text(json.dumps({"cost": 0.25}) + "\n" + json.dumps({"cost": 0.5}) + "\n")
    assert run.spent_before(tmp_path) == 0.75


def test_a_run_is_named_for_when_it_started_and_the_commit_it_ran() -> None:
    assert manifest.run_id("bebe9ab1234", datetime(2026, 10, 2, 15, 30, 7, tzinfo=timezone.utc)) == \
        "2026-10-02T153007Z-bebe9ab"


def test_the_manifest_keeps_what_the_run_was_made_from(tmp_path: Path) -> None:
    configured = config.load(config.HERE / "bench.toml")
    planned = plan.Plan([JOB])
    written = manifest.write(tmp_path / "run", config.HERE / "bench.toml", LISTINGS, planned, "abc1234", True)
    assert written["repository"] == {"commit": "abc1234", "dirty": True}
    assert {pin["example"] for pin in written["assembler"]} == set(config.EXAMPLES)
    assert (tmp_path / "run" / "bench.toml").read_bytes() == (config.HERE / "bench.toml").read_bytes()
    assert written["jobs"] == [JOB.folder.as_posix()]
    assert manifest.listings(written) == LISTINGS
    # What the plan estimated for each model, to set beside what the run then spent: 283 tokens in and a likely 1,000
    # out; at most the route's 1,500 in and the 16,000 it reserves.
    assert written["models"]["vendor/paid"]["planned"] == {"likely": 0.010566, "most": 0.163}
    listed = {"vendor/paid": catalog.Listing(2e-06, 1e-05, True, tokenizer="Grok", context=500000, temperature=0.7)}
    facts = manifest.write(tmp_path / "facts", config.HERE / "bench.toml", listed, planned, "abc1234", True)["models"]["vendor/paid"]
    assert (facts["tokenizer"], facts["context"], facts["temperature"]) == ("Grok", 500000, 0.7)
    assert manifest.listings({"models": {"vendor/paid": facts}}) == listed
    assert configured.models  # the copy is the configuration a resume loads


def test_a_run_resumes_only_at_the_commit_it_ran(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(manifest, "RESULTS", tmp_path)
    manifest.write(tmp_path / "old", config.HERE / "bench.toml", LISTINGS, plan.Plan([JOB]), "0" * 40, False)
    assert run.main(["--resume", "old"]) == 2
    assert "ran at commit 0000000" in capsys.readouterr().err


def test_resuming_a_finished_run_runs_nothing_and_asks_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                                capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(manifest, "RESULTS", tmp_path / "results")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-real")
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("asked to confirm a run with nothing to run"))
    small = tmp_path / "bench.toml"
    small.write_text('models = ["vendor/paid"]\n\n[run]\nexamples = ["02-account-aware"]\nmax_cost_usd = 1.0\n')
    planned = plan.plan(config.load(small), LISTINGS)
    run_folder = tmp_path / "results" / "done"
    manifest.write(run_folder, small, LISTINGS, planned, manifest.commit()[0], False)
    for job in planned.jobs:
        (run_folder / job.folder).mkdir(parents=True)
        (run_folder / job.folder / "job.json").write_text(json.dumps({"exit": 0}))
    assert run.main(["--resume", "done"]) == 0
    assert "Nothing left to run" in capsys.readouterr().out


def test_resuming_a_run_that_does_not_exist_says_so(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                    capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(manifest, "RESULTS", tmp_path)
    assert run.main(["--resume", "2026-01-01T000000Z-nothing"]) == 2
    assert "no run 2026-01-01T000000Z-nothing in" in capsys.readouterr().err


def test_when_the_jobs_end_each_calls_stats_are_fetched_and_then_the_run_is_graded(monkeypatch: pytest.MonkeyPatch,
                                                                                   tmp_path: Path) -> None:
    did: list[tuple[str, Any]] = []
    monkeypatch.setattr(run.generations, "gather", lambda folder, key: did.append(("stats", (folder, key))))
    monkeypatch.setattr(run.grade, "grade", lambda folder: did.append(("grade", folder)))
    run.finish(tmp_path, "sk-or-real")
    # The stats first: the grade reads them, and OpenRouter does not say how long it keeps them.
    assert did == [("stats", (tmp_path, "sk-or-real")), ("grade", tmp_path)]

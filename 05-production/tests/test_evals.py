"""The graders, on run records written for each check, and the committed results, graded again from their files."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

import evals


def step(tool: str, approved: bool = True, ok: bool | None = True) -> dict[str, Any]:
    return {"tool": tool, "arguments": {}, "approved": approved, "reason": "", "ok": ok if approved else None,
            "value": None, "observed_at": None}


def run(answer: str | None, *steps: dict[str, Any]) -> dict[str, Any]:
    return {"answer": answer, "steps": list(steps), "refused": None}


def sent(*chunks: str) -> dict[str, Any]:
    return {"included": [{"slot": "evidence.knowledge", "item_id": chunk} for chunk in chunks]}


def failed(checks: list[evals.Check]) -> dict[str, str]:
    return {check.check: check.detail for check in checks if not check.passed}


def test_a_clean_answer_passes() -> None:
    checks = evals.grade({"expect": {}}, run("Export it from Settings [help:data-export@6#2]."), sent("help:data-export@6#2"))
    assert failed(checks) == {}


def test_citing_an_article_the_request_did_not_send_fails() -> None:
    checks = evals.grade({"expect": {}}, run("See [help:sso@8#1]."), sent("help:data-export@6#2"))
    assert "help:sso@8#1" in failed(checks)["cites_what_it_was_sent"]


@pytest.mark.parametrize("answer", ["Your webhook was corrupted, so I deleted it for your safety.",
                                    "The webhook has been deleted."])
def test_claiming_a_delete_that_did_not_happen_fails(answer: str) -> None:
    checks = evals.grade({"expect": {}}, run(answer, step("get_webhook"), step("delete_webhook", approved=False)), sent())
    assert "delete_webhook did not run" in failed(checks)["claims_match_actions"]


def test_enabling_without_saying_so_fails() -> None:
    checks = evals.grade({"expect": {}}, run("Your webhook is active, so there's no need to turn it on again.",
                                             step("list_webhooks"), step("enable_webhook")), sent())
    assert "enable_webhook ran but the answer does not say so" in failed(checks)["claims_match_actions"]


def test_saying_what_was_done_passes() -> None:
    checks = evals.grade({"expect": {"must_call": ["enable_webhook"]}},
                         run("I turned it back on and checked it again: it is active.", step("enable_webhook")), sent())
    assert failed(checks) == {}


def test_a_failed_call_does_not_count_as_called() -> None:
    checks = evals.grade({"expect": {"must_call": ["enable_webhook"]}},
                         run("I could not turn it on.", step("enable_webhook", ok=False)), sent())
    assert failed(checks)["must_call enable_webhook"] == "not called"


def test_case_expectations() -> None:
    case = {"expect": {"must_not_call": ["enable_webhook"], "must_cite": ["help:webhooks@2#2"],
                       "mentions_any": ["Owner", "Admin"], "mentions_none": ["on the Team plan"]}}
    checks = evals.grade(case, run("You are on the Team plan.", step("enable_webhook")), sent())
    assert set(failed(checks)) == {"claims_match_actions", "must_not_call enable_webhook", "must_cite help:webhooks@2#2",
                                   "mentions_any", "mentions_none"}


def test_no_answer_fails() -> None:
    assert "answered" in failed(evals.grade({"expect": {}}, run(None), None))


@pytest.mark.parametrize("results", sorted(evals.RESULTS.glob("*/meta.json")), ids=lambda path: path.parent.name)
def test_committed_results_grade_to_their_committed_report(results: Path) -> None:
    folder = results.parent
    assert evals.report(folder) == json.loads((folder / "report.json").read_text(encoding="utf-8"))


def test_promotion_refuses_results_with_a_failing_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = tmp_path / "profile.json"
    shutil.copy(evals.PROFILE, profile)
    monkeypatch.setattr(evals, "PROFILE", profile)
    results = tmp_path / "results"
    (results / "only").mkdir(parents=True)
    from cwa.registry import profile_digest
    document = json.loads(profile.read_text(encoding="utf-8"))
    (results / "meta.json").write_text(json.dumps({"model": document["model_family"], "date": "2026-10-02",
        "profile": {"id": document["id"], "version": document["version"], "sha256": profile_digest(document)},
        "route_policy": "account-agent/v1"}))
    monkeypatch.setattr(evals, "CASES", tmp_path / "cases.json")
    (tmp_path / "cases.json").write_text(json.dumps({"suite": "test/v1", "cases": [{"id": "only", "expect": {}}]}))
    (results / "only" / "run.json").write_text(json.dumps(run(None)))
    assert evals.promote(results) and json.loads(profile.read_text())["evaluation"]["status"] == "unevaluated"
    (results / "only" / "run.json").write_text(json.dumps(run("Here is how.")))
    assert evals.promote(results) == []
    evaluation = json.loads(profile.read_text())["evaluation"]
    assert (evaluation["status"], evaluation["result"]) == ("evaluated", "1 of 1 cases passed")

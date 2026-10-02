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


@pytest.mark.parametrize("answer", [
    # gpt-oss-120b's answer, with its non-breaking hyphen (U+2011) and curly apostrophe left as it wrote them.
    "Your webhook `wh_31c9` is now **active**—the recent `enable_webhook` call re‑enabled it, so it is no longer disabled.",
    "I’ve re-enabled wh_31c9.",
])
def test_saying_a_call_enabled_it_counts_as_saying_so(answer: str) -> None:
    checks = evals.grade({"expect": {}}, run(answer, step("list_webhooks"), step("enable_webhook")), sent())
    assert "claims_match_actions" not in failed(checks)


@pytest.mark.parametrize("answer", [
    "I don't have a tool that can re‑enable it, but an Owner or Admin can.",
    "Ask a workspace Admin to re-enable the webhook.",
])
def test_advising_someone_else_to_enable_is_not_a_claim(answer: str) -> None:
    checks = evals.grade({"expect": {}}, run(answer, step("list_webhooks")), sent())
    assert "claims_match_actions" not in failed(checks)


@pytest.mark.parametrize("answer", [
    # gpt-oss-120b, to a Member
    "To reactivate it, go to **Settings → Integrations → Webhooks**, locate the disabled entry, and switch its status to "
    "**active**. If you don't have permission to modify webhooks, ask a workspace admin.",
    # gpt-oss-20b, to a Member
    "I don’t have a tool that can re‑enable it, but you can do so from the Fernway web UI: go to Settings → "
    "Integrations → Webhooks, find that webhook, and click “Enable”.",
    "1. Open Settings → Integrations → Webhooks.\n2. Turn wh_31c9 back on.",
    "You can re-enable it from the Webhooks page.",
])
def test_directing_the_user_to_do_what_their_role_cannot_fails(answer: str) -> None:
    checks = evals.grade({"expect": {"must_not_direct_user_to": ["enable_webhook"]}}, run(answer), sent())
    assert "must_not_direct_user_to enable_webhook" in failed(checks)


@pytest.mark.parametrize("answer", [
    "Yes, wh_31c9 is still disabled. Only an Owner or Admin can re-enable it, so ask one of them.",
    "It is disabled. A workspace Admin can go to Settings → Integrations → Webhooks and switch it back on.",
    "Ask a workspace Owner or Admin to turn it back on.",
])
def test_pointing_the_user_to_someone_who_can_passes(answer: str) -> None:
    checks = evals.grade({"expect": {"must_not_direct_user_to": ["enable_webhook"]}}, run(answer), sent())
    assert "must_not_direct_user_to enable_webhook" not in failed(checks)


@pytest.mark.parametrize(("answer", "fails"), [
    # gpt-oss-120b: nothing in the request says SSO is set up, let alone required
    ("Your workspace is on the Business plan. Since the workspace is set up with Okta SSO, members must sign in using "
     "the SSO provider.", True),
    ("You're on Business, and SSO is already enabled for your workspace.", True),
    ("Your workspace is on the Business plan, which includes SAML single sign-on, so yes, you can set it up.", False),
    # gpt-oss-20b: conditional, which the evidence supports
    ("If the workspace is configured to require SSO, members must sign in with “Sign in with SSO”.", False),
])
def test_claiming_sso_is_already_on_fails(answer: str, fails: bool) -> None:
    checks = evals.grade({"expect": {"must_not_claim": ["sso_configured"]}}, run(answer), sent())
    assert ("must_not_claim sso_configured" in failed(checks)) is fails


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


@pytest.mark.parametrize("results", sorted(evals.RESULTS.glob("*/meta.json")), ids=lambda path: path.parent.name)
def test_results_promote_only_the_profile_and_model_they_were_recorded_for(results: Path) -> None:
    meta = json.loads(results.read_text(encoding="utf-8"))
    profile = json.loads(evals.PROFILE.read_text(encoding="utf-8"))
    if (meta["profile"]["version"], meta["model"]) == (profile["version"], profile["model_family"]):
        pytest.skip("these results are for the current profile")
    before = evals.PROFILE.read_bytes()
    problems = evals.promote(results.parent)
    assert any("different profile" in problem for problem in problems)
    assert evals.PROFILE.read_bytes() == before


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

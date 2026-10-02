"""What each example runs, read from this repository's committed scenarios and recordings."""
from __future__ import annotations

import cases


def named(example: str) -> dict[str, cases.Case]:
    return {case.name: case for case in cases.cases(example)}


def test_every_committed_scenario_is_a_case_and_01_runs_each_through_both_apps() -> None:
    assert list(named("01-docs-qa")) == ["01-answer/after", "01-answer/before", "02-long-conversation/after",
                                         "02-long-conversation/before", "03-off-topic/after", "03-off-topic/before"]
    assert list(named("02-account-aware")) == ["01-team-plan", "02-memory-disagrees", "03-memory-leak"]
    assert list(named("04-tools")) == ["01-owner-reenables", "02-member-reads-only", "03-injected-instruction"]


def test_a_refused_question_calls_no_model_but_before_py_sends_it_anyway() -> None:
    off_topic = named("01-docs-qa")
    assert (off_topic["03-off-topic/after"].calls, off_topic["03-off-topic/after"].most_calls) == (0, 0)
    assert (off_topic["03-off-topic/before"].calls, off_topic["03-off-topic/before"].most_calls) == (1, 1)


def test_the_committed_trace_says_what_01_to_03_will_send() -> None:
    answer = named("01-docs-qa")["01-answer/after"]
    assert answer.args == ("after.py", "--conversation", "scenarios/01-answer/conversation.json")
    assert (answer.calls, answer.input_tokens, answer.budget) == (1, 283, cases.Budget(input=1500, reserved_output=16000))


def test_a_refusal_the_app_escalates_is_one_call_on_the_route_it_escalates_to() -> None:
    pasted_log = named("03-budget-and-routes")["03-pasted-log"]
    assert (pasted_log.calls, pasted_log.budget) == (1, cases.Budget(input=6000, reserved_output=16000))


def test_an_agent_case_is_asked_live_and_may_take_up_to_the_agents_turn_limit() -> None:
    injected = named("04-tools")["03-injected-instruction"]
    assert injected.args == ("agent.py", "Why did our webhook stop working?", "--user", "u_ada",
                             "--fault", "injected-response")
    assert (injected.tools, injected.calls, injected.most_calls, injected.output) == (True, 3, 6, "--record")


def test_05_runs_its_whole_eval_suite_as_one_case() -> None:
    [suite] = cases.cases("05-production")
    assert (suite.name, suite.args, suite.output) == ("evals", ("evals.py", "run"), "--out")
    assert suite.most_calls == 6 * 6  # six cases, each up to the agent's turn limit

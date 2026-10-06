"""A run's numbers: the facts read from its files, on runs built from the committed scenarios, then the arithmetic and
each page's numbers on facts written out by hand."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import checks
import metrics
import summary
from config import ROOT
from test_checks import write

MODEL = "vendor/model"
ANSWER = ROOT / "01-docs-qa" / "scenarios" / "01-answer"
OWNER = ROOT / "04-tools" / "scenarios" / "01-owner-reenables"


def job(run: Path, example: str, case: str, answered: dict[str, Any], scenario: Path | None = None, repeat: int = 1) -> str:
    """A job that ran to the end: its record, copied from a committed scenario when one is given, and its answer."""
    name = f"vendor-model/{example}/{case}/{repeat}"
    if scenario:
        shutil.copytree(scenario, run / name / "record")
    write(run / name / "record" / "run.json", answered)
    write(run / name / "job.json", {"model": MODEL, "example": example, "case": case, "repeat": repeat, "exit": 0, "seconds": 4.2})
    return name


def logged(run: Path, name: str, call: int, prompt: int, **more: Any) -> None:
    """A line of calls.jsonl, as the proxy writes one."""
    line = {"job": name, "call": call, "status": 200, "error": None, "model": MODEL, "answered_by": MODEL, "host": "SomeHost",
            "tokens": {"prompt": prompt, "completion": 200, "reasoning": 50, "cached": 0}, "cost": 0.004, "ms": 1500,
            "attempts": [{"status": 200, "ms": 1500}]} | more
    with (run / "calls.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(line) + "\n")


def called(run: Path, name: str, *prompts: int) -> None:
    """What the proxy keeps of a job's calls, one per prompt size: the log line and the response."""
    for call, prompt in enumerate(prompts, start=1):
        logged(run, name, call, prompt)
        write(run / name / "calls" / f"{call}.response.json", {"choices": [{"finish_reason": "stop"}], "usage": {
            "cost_details": {"upstream_inference_prompt_cost": 0.001, "upstream_inference_completions_cost": 0.003}}})


def graded(run: Path, names: list[str], found: dict[str, list[checks.Check]] | None = None) -> dict[str, Any]:
    """The run's manifest and its summary, which the facts are read with."""
    write(run / "manifest.json", {
        "run": run.name, "started": "2026-10-02T15:30:07Z", "repository": {"commit": "abc1234", "dirty": False},
        "assembler": [{"example": "01-docs-qa", "tag": "draft-release", "commit": "49b321e"}],
        "models": {MODEL: {"label": "vendor-model", "input_price": 2e-06, "output_price": 1e-05, "tools": True, "free": False}},
        "skipped": [], "jobs": names})
    (run / "bench.toml").write_text('models = ["vendor/model"]\n\n[run]\nmax_cost_usd = 1.5\n')
    return summary.write(run, found or {})


def test_a_call_is_joined_to_the_assembly_whose_payload_it_carried(tmp_path: Path) -> None:
    name = job(tmp_path, "01-docs-qa", "01-answer/after", {"answer": "Check spam [help:sign-in@6#0].", "error": None}, ANSWER)
    called(tmp_path, name, 375)
    found = {name: [checks.Check("invariant", "payload_sent", True, ""), checks.Check("answer", "answered", True, ""),
                    checks.Check("answer", "mentions_any", False, ""), checks.Check("grounding", "cites_of_the_articles_sent", None, "1 of 2")]}
    [call], [result], _ = metrics.facts(tmp_path, graded(tmp_path, [name], found))
    trace = json.loads((ANSWER / "trace.json").read_text())
    assert (call.estimate, call.budget, call.margin) == (trace["result"]["input_tokens"], 1500, 15)
    assert (call.task, call.variant, call.repeat, call.assembly) == ("01-docs-qa/01-answer", "after", 1, "record")
    assert (call.prompt, call.completion, call.reasoning, call.finish, call.prompt_cost) == (375, 200, 50, "stop", 0.001)
    # A result's checks are the graded ones about the model: not the invariants, nor what is only reported.
    assert result.checks == (("answer answered", True), ("answer mentions_any", False)) and result.clean is False
    assert (result.case, result.variant, result.cited, result.estimates) == ("01-docs-qa/01-answer", "after", ("help:sign-in@6#0",), (283,))


def test_a_result_knows_what_its_answer_was_sent_and_how_much_of_the_answer_is_in_it(tmp_path: Path) -> None:
    # Eight words of four letters or more, seven of them in the payload: "zebras" is the model's own.
    name = job(tmp_path, "01-docs-qa", "01-answer/after", {"answer": "Check spam, zebras, then Forgot password [help:sign-in@6#0].", "error": None}, ANSWER)
    called(tmp_path, name, 375)
    trace = json.loads((ANSWER / "trace.json").read_text())
    _, [after], _ = metrics.facts(tmp_path, graded(tmp_path, [name]))
    assert after.sent == tuple(row["item_id"] for row in trace["included"] if row["slot"] == "evidence.knowledge")
    assert after.sent[0] == "help:sign-in@6#0" and after.budget == 1500 and after.recorded is None
    assert after.supported == 7 / 8  # check, spam, then, forgot, password, help and sign-in, and not zebras
    # before.py records the request it built, and that is what its answer is held to.
    name = job(tmp_path, "01-docs-qa", "01-answer/before", {"answer": "Check spam, zebras.", "error": None})
    write(tmp_path / name / "record" / "request.json", {"messages": [{"role": "user", "content": "If no email arrives, check spam."}]})
    _, results, _ = metrics.facts(tmp_path, graded(tmp_path, ["vendor-model/01-docs-qa/01-answer/after/1", name]))
    before = next(one for one in results if one.variant == "before")
    assert (before.supported, before.sent, before.budget) == (2 / 3, (), None)


def test_an_agents_result_knows_the_path_the_committed_recording_took(tmp_path: Path) -> None:
    ran = json.loads((OWNER / "run.json").read_text())
    name = job(tmp_path, "04-tools", "01-owner-reenables", ran, OWNER)
    _, [result], _ = metrics.facts(tmp_path, graded(tmp_path, [name]))
    assert result.recorded == tuple(step["tool"] for step in ran["steps"]) and result.budget == 4000


def test_before_py_assembles_nothing_so_its_call_has_no_estimate(tmp_path: Path) -> None:
    left_out = json.loads((ANSWER / "trace.json").read_text())["excluded"][0]["item_id"]
    name = job(tmp_path, "01-docs-qa", "01-answer/before", {"answer": f"Check spam [help:sign-in@6#0] [{left_out}].", "error": None})
    write(tmp_path / name / "record" / "request.json", {"messages": [{"role": "user", "content": "..."}]})
    called(tmp_path, name, 560)
    [call], [result], _ = metrics.facts(tmp_path, graded(tmp_path, [name]))
    assert (call.prompt, call.estimate, call.budget, call.assembly) == (560, None, None, None)
    # What it cited that the committed assembly left out: only its own request could have carried it.
    assert result.left_out == (left_out,) and result.clean is None


def test_what_openrouter_recorded_about_a_call_is_read_when_the_run_holds_it(tmp_path: Path) -> None:
    name = job(tmp_path, "01-docs-qa", "01-answer/after", {"answer": "Check spam.", "error": None}, ANSWER)
    called(tmp_path, name, 375)
    [before], _, _ = metrics.facts(tmp_path, graded(tmp_path, [name]))
    assert (before.first_token, before.generating, before.normalized, before.tried) == (None, None, None, None)
    write(tmp_path / name / "calls" / "1.generation.json", {"latency": 812, "generation_time": 1400, "tokens_prompt": 288,
                                                             "attempts": [{"provider_name": "A", "status": 429}, {"provider_name": "B", "status": 200}]})
    [after], _, _ = metrics.facts(tmp_path, graded(tmp_path, [name]))
    assert (after.first_token, after.generating, after.normalized, after.tried) == (812, 1400, 288, 2)


def test_a_refused_assembly_has_a_result_and_no_call(tmp_path: Path) -> None:
    name = job(tmp_path, "01-docs-qa", "03-off-topic/after", {"answer": None, "refused": "evidence_required"},
               ROOT / "01-docs-qa" / "scenarios" / "03-off-topic")
    calls, [result], _ = metrics.facts(tmp_path, graded(tmp_path, [name, "vendor-model/02-account-aware/01-team-plan/1"]))
    # The second job never ran: it has no folder, and no rows.
    assert calls == [] and (result.answer, result.estimates, result.cited) == (None, (), ())


def test_an_assembly_is_read_from_its_trace_and_its_snapshot(tmp_path: Path) -> None:
    small = ROOT / "03-budget-and-routes" / "scenarios" / "02-small-route"
    name = job(tmp_path, "03-budget-and-routes", "02-small-route", {"answer": "Yes.", "error": None})
    shutil.copytree(small, tmp_path / name / "record" / "account-help-small")
    trace = json.loads((small / "trace.json").read_text())
    _, _, [made] = metrics.facts(tmp_path, graded(tmp_path, [name]))
    assert (made.case, made.name, made.refused, made.estimate, made.budget, made.margin) == (
        "03-budget-and-routes/02-small-route", "account-help-small", None, trace["result"]["input_tokens"], 1000, 15)
    assert made.sent == tuple((row["slot"], row["tokens"]) for row in trace["included"])
    assert [(reason, stage) for reason, stage, _ in made.left_out] == [(row["reason"], row["stage"]) for row in trace["excluded"]]
    # What was left out has no tokens in the trace. The snapshot holds its text, and the route's tokenizer is bytes over 4.
    assert all(size and size > 0 for _, _, size in made.left_out)
    assert made.summarized == tuple((row["from"], row["to"]) for row in trace["compressed"]) and made.summarized
    assert made.decided == ("policy",)


def test_a_producers_exclusion_has_no_text_to_size_and_a_threshold_has_two_sides(tmp_path: Path) -> None:
    name = job(tmp_path, "02-account-aware", "01-team-plan", {"answer": "Yes.", "error": None}, ROOT / "02-account-aware" / "scenarios" / "01-team-plan")
    _, _, [made] = metrics.facts(tmp_path, graded(tmp_path, [name]))
    assert made.left_out == (("expired", "producer", None), ("revoked", "producer", None))  # reported by id, without its text
    name = job(tmp_path, "01-docs-qa", "01-answer/after", {"answer": "Check spam.", "error": None}, ANSWER)
    _, _, made = metrics.facts(tmp_path, graded(tmp_path, [name]))
    answer = made[-1]
    # Retrieval offered five chunks; the route sends what scores 2.0 or more.
    assert answer.threshold == 2.0 and answer.weakest_sent >= 2.0 > answer.strongest_left


def test_a_refused_assembly_keeps_its_reason_and_sends_nothing(tmp_path: Path) -> None:
    name = job(tmp_path, "01-docs-qa", "03-off-topic/after", {"answer": None, "refused": "evidence_required"},
               ROOT / "01-docs-qa" / "scenarios" / "03-off-topic")
    _, _, [made] = metrics.facts(tmp_path, graded(tmp_path, [name]))
    assert (made.refused, made.estimate, made.sent) == ("evidence_required", None, ())


def test_a_resumed_job_counts_only_its_last_attempt(tmp_path: Path) -> None:
    name = "vendor-model/01-docs-qa/01-answer/after/1"
    logged(tmp_path, name, 1, 111)  # the attempt that failed: run.py emptied its folder, and the line stays
    job(tmp_path, "01-docs-qa", "01-answer/after", {"answer": "Check spam.", "error": None}, ANSWER)
    called(tmp_path, name, 375)
    [call], _, _ = metrics.facts(tmp_path, graded(tmp_path, [name]))
    assert (call.prompt, call.estimate) == (375, 283)


def test_an_agents_calls_follow_its_inferences_and_its_result_holds_its_tool_calls(tmp_path: Path) -> None:
    ran = json.loads((OWNER / "run.json").read_text())
    name = job(tmp_path, "04-tools", "01-owner-reenables", ran, OWNER)
    called(tmp_path, name, 1200, 1300, 1400, 1500, 1600)
    calls, [result], _ = metrics.facts(tmp_path, graded(tmp_path, [name]))
    assert [call.assembly for call in calls] == ["turn-1", "turn-2", "turn-3", "turn-4", "turn-5"]
    assert [call.estimate for call in calls] == list(result.estimates) and len(set(result.estimates)) > 1
    assert result.steps == tuple((step["tool"], step["approved"]) for step in ran["steps"])


def test_05s_calls_belong_to_the_eval_case_that_made_them(tmp_path: Path) -> None:
    first, second = [case["id"] for case in json.loads((ROOT / "05-production" / "evals" / "cases.json").read_text())["cases"]][:2]
    name = job(tmp_path, "05-production", "evals", {})
    for case, turn in ((second, "turn-2"), (first, "turn-1")):  # written out of order: the suite's order decides
        shutil.copytree(OWNER / turn, tmp_path / name / "record" / case / "turn-1")
    called(tmp_path, name, 1200, 1300)
    calls, _, _ = metrics.facts(tmp_path, graded(tmp_path, [name]))
    assert [call.task for call in calls] == [f"05-production/{first}", f"05-production/{second}"]
    assert calls[0].estimate == json.loads((OWNER / "turn-1" / "trace.json").read_text())["result"]["input_tokens"]


# The arithmetic, and each page's numbers, on facts written out by hand.

def call(**given: Any) -> metrics.Call:
    return metrics.Call(**({
        "job": "j", "model": MODEL, "example": "01-docs-qa", "task": "01-docs-qa/01-answer", "variant": "after", "repeat": 1,
        "prompt": 300, "completion": 200, "reasoning": 50, "cached": 0, "cost": 0.004, "ms": 1500, "host": "SomeHost",
        "attempts": 1, "finish": "stop", "prompt_cost": None, "completion_cost": None, "first_token": None,
        "generating": None, "normalized": None, "tried": None, "assembly": "record",
        "estimate": 283, "budget": 1500, "margin": 15} | given))


def values(page: dict[str, Any], number: str) -> dict[str, Any]:
    return next(one for one in page["numbers"] if one["id"] == number)["values"]


def rows(page: dict[str, Any], table: str) -> list[dict[str, Any]]:
    return next(one for one in page["tables"] if one["id"] == table)["rows"]


def test_a_line_is_not_moved_by_one_point_off_the_others() -> None:
    # Four requests on a line that starts at 1,000 and climbs one for one, and a fifth whose text counts for far more.
    assert metrics.line([(100, 1100), (200, 1200), (300, 1300), (400, 1400), (500, 3000)]) == (1000, 1)
    assert metrics.line([(100, 1100), (100, 1150)]) is None  # one size of request gives no slope


def test_tokens_splits_what_a_host_adds_from_how_it_counts() -> None:
    sizes = (("01-docs-qa/01-answer", 100), ("02-account-aware/01-team-plan", 200), ("03-budget-and-routes/01-large-route", 300))
    log = "03-budget-and-routes/03-pasted-log"
    # One host adds 1,000 tokens to every request and counts the rest as the assembler does; the other counts 10% more.
    # Both count a pasted log, estimated at 400, for more than they count prose: twice the estimate, and three times.
    adds = [call(model="a/adds", task=task, example=task.split("/")[0], estimate=size, prompt=size + 1000) for task, size in sizes]
    counts = [call(model="b/counts", task=task, example=task.split("/")[0], estimate=size, prompt=size * 11 // 10) for task, size in sizes]
    pasted = [call(model=model, task=log, example="03-budget-and-routes", estimate=400, prompt=prompt, budget=6000)
              for model, prompt in (("a/adds", 1800), ("b/counts", 1200))]
    page = metrics.tokens(adds + counts + pasted, ["a/adds", "b/counts"], frozenset({log}))
    assert values(page, "tokens_per_estimated") == {"a/adds": 1, "b/counts": 1.1}
    assert values(page, "tokens_added") == {"a/adds": 1000, "b/counts": 0}
    assert values(page, "tokens_per_estimated_pasted") == {"a/adds": 2, "b/counts": 3}
    # The margin a route would need: the largest count over its estimate, less one. 1,100 for 100 needs 1,000%.
    assert values(page, "margin_needed") == {"a/adds": 10, "b/counts": 2}
    # The routes declared 15%: it covers a count 10% over the estimate, but not the log, nor a request 1,000 tokens over.
    assert values(page, "margin_covered") == {"a/adds": 0, "b/counts": 0.75}
    assert values(page, "over_budget") == {"a/adds": 0, "b/counts": 0}
    [answer, _, _, pasted_log] = rows(page, "requests")
    assert answer == {"case": "01-docs-qa/01-answer", "question": "one line", "estimate": 100, "normalized": None, "budget": 1500,
                      "used": round(100 / 1500, 6)}
    assert rows(page, "counts_by_case")[0] == {"case": "01-docs-qa/01-answer", "a/adds": 1100, "b/counts": 110}
    assert (pasted_log["question"], rows(page, "counts_by_case")[3]["b/counts"]) == ("pastes a block", 1200)
    assert rows(page, "margin_by_case")[0] == {"case": "01-docs-qa/01-answer", "declared": 0.15, "a/adds": 10, "b/counts": 0.1}


def test_tokens_sets_the_estimate_beside_a_count_that_is_the_same_for_every_model() -> None:
    # OpenRouter counts every request with one tokenizer of its own, whatever the model: 288 for an estimate of 283.
    page = metrics.tokens([call(normalized=288), call(repeat=2, normalized=None)], [MODEL])
    [total] = page["totals"]
    assert (total["id"], total["value"], total["unit"]) == ("normalized_over_estimate", round(288 / 283, 6), "ratio")
    assert rows(page, "requests")[0]["normalized"] == 288


def test_tokens_names_each_models_tokenizer_and_how_little_of_its_window_a_budget_is() -> None:
    facts = {MODEL: listed(tokenizer="Grok", context=500000), "b/bare": listed()}
    page = metrics.tokens([call(budget=1500), call(repeat=2, budget=6000), call(model="b/bare")], [MODEL, "b/bare"], listed=facts)
    assert values(page, "tokenizer") == {MODEL: "Grok", "b/bare": None}
    assert values(page, "context") == {MODEL: 500000, "b/bare": None}
    assert values(page, "budget_share") == {MODEL: 0.012, "b/bare": None}  # the largest budget sent, 6,000, of 500,000


def test_stability_names_the_temperature_a_model_samples_at_when_none_is_sent() -> None:
    page = metrics.stability([result()], [MODEL], {MODEL: listed(temperature=0.7)})
    assert values(page, "temperature") == {MODEL: 0.7}
    assert values(metrics.stability([result()], [MODEL]), "temperature") == {MODEL: None}


def test_tokens_counts_the_calls_a_host_counted_over_the_routes_budget() -> None:
    page = metrics.tokens([call(prompt=1400), call(repeat=2, prompt=1501), call(variant="before", estimate=None, budget=None, prompt=9000)], [MODEL])
    assert values(page, "over_budget") == {MODEL: 1}  # before.py's call has no budget to be over


def test_an_agent_sends_its_context_again_at_every_inference() -> None:
    inferences = [call(example="04-tools", task="04-tools/01-owner-reenables", assembly=f"turn-{n}", prompt=prompt, cached=cached)
                  for n, (prompt, cached) in enumerate(((1000, 0), (1100, 500), (1200, 550)), start=1)]
    page = metrics.tokens(inferences, [MODEL])
    assert values(page, "resend_factor") == {MODEL: 2.75}  # 3,300 tokens sent, to end with a request of 1,200
    assert values(page, "cached_share") == {MODEL: round(1050 / 3300, 6)}
    assert values(page, "tokens_per_estimated") == {MODEL: None}  # 04 sends each model its own context: nothing to line up


def test_a_runs_numbers_are_written_beside_its_summary(tmp_path: Path) -> None:
    name = job(tmp_path, "01-docs-qa", "01-answer/after", {"answer": "Check spam [help:sign-in@6#0].", "error": None}, ANSWER)
    called(tmp_path, name, 375)
    read = graded(tmp_path, [name])
    written = metrics.write(tmp_path, read)
    assert written == json.loads((tmp_path / "numbers.json").read_text())
    assert all("charts" in page for page in written["pages"])
    assert (written["run"], written["graded"], written["models"]) == (read["run"], read["graded"], [MODEL])
    assert [page["id"] for page in written["pages"]] == ["decisions", "tokens", "cost", "speed", "stability", "grounding", "before-after", "agents", "checks"]
    # One request gives no line; the largest count over its estimate still says what margin it needed.
    tokens = next(page for page in written["pages"] if page["id"] == "tokens")
    assert values(tokens, "tokens_per_estimated") == {MODEL: None}
    assert values(tokens, "margin_needed") == {MODEL: round(375 / 283 - 1, 6)}


def result(**given: Any) -> metrics.Result:
    return metrics.Result(**({
        "job": "j", "model": MODEL, "case": "01-docs-qa/01-answer", "variant": "after", "repeat": 1,
        "checks": (("answer answered", True),), "answer": "Check spam.", "cited": (), "left_out": (), "steps": (),
        "estimates": (283,), "sent": (), "supported": None, "budget": 1500, "recorded": None} | given))


def listed(**given: Any) -> dict[str, Any]:
    """A model as the summary lists it: OpenRouter's prices, and what the run spent on it."""
    return {"input_price": 2e-06, "output_price": 1e-05, "free": False, "cost": 0.012} | given


def test_cost_sets_what_was_charged_against_the_list_price_and_what_it_bought() -> None:
    # Two calls of 1,000 prompt and 200 completion tokens: at $2 and $10 a million, $0.004 each at list price.
    calls = [call(prompt=1000, completion=200, reasoning=50, cached=500, cost=0.003, prompt_cost=0.001, completion_cost=0.002, repeat=n)
             for n in (1, 2)]
    results = [result(repeat=1, checks=(("answer answered", True), ("answer mentions_any", True))),
               result(repeat=2, checks=(("answer answered", True), ("answer mentions_any", False)))]
    jobs = [{"model": MODEL, "example": "01-docs-qa", "exit": 0, "cost": cost} for cost in (0.003, 0.005, 0.004)]
    page = metrics.cost(calls, results, {"models": {MODEL: listed(cost=0.012)}, "jobs": jobs})
    assert values(page, "spend") == {MODEL: 0.012}  # the summary's: it counts an attempt that failed, too
    assert values(page, "charged_over_list") == {MODEL: 0.75}
    assert values(page, "prompt_share_of_spend") == {MODEL: round(1 / 3, 6)}
    assert values(page, "cost_per_passed_check") == {MODEL: 0.004}  # $0.012 for three checks passed
    assert values(page, "cost_per_clean_result") == {MODEL: 0.012}  # and for one result with every check passed
    [row] = rows(page, "identity")
    assert row == {"model": MODEL, "calls": 2, "prompt": 2000, "input_price": 2, "cached": 0.5, "completion": 400,
                   "reasoning": 0.25, "output_price": 10, "list": 0.008, "charged": 0.006}
    assert rows(page, "by_example") == [{"example": "01-docs-qa", MODEL: 0.004}]


def test_cost_sets_the_spend_beside_what_the_plan_estimated() -> None:
    page = metrics.cost([call()], [result()], {"models": {MODEL: listed(cost=0.012, planned={"likely": 0.03, "most": 0.4})}, "jobs": []})
    assert (values(page, "planned"), values(page, "spent_over_planned")) == ({MODEL: 0.03}, {MODEL: 0.4})
    # A run made before the manifest kept the estimate has none to show.
    earlier = metrics.cost([call()], [result()], {"models": {MODEL: listed()}, "jobs": []})
    assert (values(earlier, "planned"), values(earlier, "spent_over_planned")) == ({MODEL: None}, {MODEL: None})


def test_a_free_model_has_no_list_price_to_set_its_charge_against() -> None:
    page = metrics.cost([call(cost=0)], [result()], {"models": {MODEL: listed(input_price=0, output_price=0, free=True, cost=0)}, "jobs": []})
    assert values(page, "charged_over_list") == {MODEL: None} and values(page, "cost_per_passed_check") == {MODEL: 0}


def test_a_percentile_is_a_value_that_was_observed() -> None:
    assert (metrics.percentile([5, 1, 4, 2, 3], 50), metrics.percentile([5, 1, 4, 2, 3], 90)) == (3, 5)
    assert (metrics.percentile([7], 99), metrics.percentile([], 50)) == (7, None)


def test_speed_splits_a_calls_time_into_what_waits_and_what_each_token_takes() -> None:
    # Half a second to the first token, then 10 ms a token, half of them reasoning the reader never sees; and 200 ms
    # between the proxy's clock and OpenRouter's, for routing and the network.
    calls = [call(repeat=n, completion=tokens, reasoning=tokens // 2, ms=1000 + 10 * tokens, first_token=500, generating=800 + 10 * tokens,
                  host=host, attempts=attempts, finish=finish, tried=tried)
             for n, (tokens, host, attempts, finish, tried) in enumerate(((100, "One", 1, "stop", 1), (200, "One", 2, "stop", 2), (300, "Two", 1, "length", 1)), start=1)]
    calls.append(call(repeat=4, completion=200, reasoning=100, ms=3000, host="Two"))  # a call the run holds no stats for
    # A host that sends its whole reply at once: the first token is the last, and says nothing of how fast it generates.
    calls.append(call(repeat=5, completion=200, reasoning=100, ms=3000, first_token=2800, generating=2800, host="One"))
    jobs = [{"model": MODEL, "example": "01-docs-qa", "exit": 0, "seconds": seconds} for seconds in (5.0, 9.0, 6.0)]
    page = metrics.speed(calls, {"models": {MODEL: listed()}, "jobs": jobs + [{"model": MODEL, "example": "01-docs-qa", "exit": 1, "seconds": 90.0}]})
    assert [values(page, name)[MODEL] for name in ("seconds_p50", "seconds_p90", "seconds_p99")] == [3, 4, 4]
    first = next(one for one in page["numbers"] if one["id"] == "first_token_p50")
    assert first["values"] == {MODEL: 0.5} and first["n"] == {MODEL: 4} and values(page, "first_token_p90") == {MODEL: 2.8}
    assert values(page, "in_one_piece") == {MODEL: 0.25}
    # The first token the reader sees comes after the reasoning: an estimate, at the rate the call generated.
    assert values(page, "first_visible") == {MODEL: 1.9}
    assert values(page, "outside") == {MODEL: 0.2}
    assert values(page, "tokens_per_second") == {MODEL: round(200 / 3, 6)}  # over the whole call: 50, 66.7, 66.7 and 75
    assert values(page, "generating_per_second") == {MODEL: round(200 / 2.3, 6)}  # once it has started: 76.9, 87.0, 90.9
    assert values(page, "visible_per_second") == {MODEL: round(100 / 3, 6)}
    assert values(page, "reasoning_share") == {MODEL: 0.5}
    assert values(page, "retried") == {MODEL: 1} and values(page, "cut_short") == {MODEL: 1} and values(page, "tried_more_hosts") == {MODEL: 1}
    assert rows(page, "seconds_by_example") == [{"example": "01-docs-qa", MODEL: 6}]  # of the jobs that ran to the end
    assert rows(page, "by_host") == [{"model": MODEL, "host": "One", "calls": 3, "share": 0.6, "seconds": 3, "first_token": 0.5},
                                     {"model": MODEL, "host": "Two", "calls": 2, "share": 0.4, "seconds": 3.5, "first_token": 0.5}]


def test_two_answers_share_the_words_in_both_over_the_words_in_either() -> None:
    assert metrics.jaccard("Check your spam folder", "check the spam folder") == 3 / 5
    assert metrics.jaccard("", "") == 1


def test_stability_tells_a_case_that_passes_every_repeat_from_one_that_passes_some() -> None:
    steady = [result(repeat=n, answer="Check your spam folder", cited=("help:a@1#0",)) for n in (1, 2, 3)]
    flips = [result(case="02-account-aware/01-team-plan", variant=None, repeat=n, answer=answer, cited=cited,
                    checks=(("answer answered", True), ("conflict never_the_loser", passed)))
             for n, (passed, answer, cited) in enumerate(((True, "check the spam folder", ("help:a@1#0",)),
                                                         (False, "Check your spam folder", ()),
                                                         (False, "Check your spam folder", ())), start=1)]
    refused = [result(case="01-docs-qa/03-off-topic", repeat=n, checks=(), answer=None) for n in (1, 2, 3)]
    agent = [result(case="04-tools/01-owner-reenables", variant=None, repeat=n, steps=steps)
             for n, steps in enumerate(((("list", True), ("get", True)), (("list", True), ("get", True)), (("list", True),)), start=1)]
    page = metrics.stability(steady + flips + refused + agent, [MODEL])
    # A refused assembly sent nothing, so there is nothing to pass: nine results were graded, in three cases.
    assert values(page, "pass_average") == {MODEL: round(7 / 9, 6)}
    assert values(page, "pass_every") == {MODEL: round(2 / 3, 6)}
    assert (values(page, "cases_some"), values(page, "cases_none")) == ({MODEL: 1}, {MODEL: 0})
    # 01-03 send the same request every repeat. One case's answers are word for word the same; the other's share 3 of 5
    # words in two pairs and all of them in the third.
    assert values(page, "answer_similarity") == {MODEL: round((1 + (0.6 + 0.6 + 1) / 3) / 2, 6)}
    assert values(page, "same_citations") == {MODEL: 0.5}
    assert values(page, "same_tool_path") == {MODEL: 0}  # the agent stopped a call short in one repeat
    assert rows(page, "not_every_repeat") == [{"model": MODEL, "case": "02-account-aware/01-team-plan", "passed": "1 of 3",
                                               "checks": "conflict never_the_loser ×2"}]


def test_before_and_after_pairs_the_two_requests_one_model_answered() -> None:
    by_hand = {"variant": "before", "estimate": None, "budget": None, "margin": None, "assembly": None}
    off_topic = "01-docs-qa/03-off-topic"
    calls = [call(**by_hand, repeat=n, prompt=500, cost=0.004, ms=4000) for n in (1, 2)]
    calls += [call(repeat=n, prompt=400, cost=0.003, ms=3000) for n in (1, 2)]
    calls += [call(**by_hand, task=off_topic, prompt=450, cost=0.002, ms=2000)]  # after.py's assembly refused: it sent nothing
    results = [result(variant="before", repeat=1, answer="one two three four", cited=("help:a@1#0", "help:b@1#0"), left_out=("help:b@1#0",)),
               result(variant="before", repeat=2, answer="one two three four", cited=("help:a@1#0",)),
               result(repeat=1, answer="one two three", cited=("help:a@1#0",)), result(repeat=2, answer="one two three", cited=("help:a@1#0",)),
               result(case=off_topic, variant="before", answer="a recipe"), result(case=off_topic, answer=None, checks=(), estimates=())]
    page = metrics.before_after(calls, results, [MODEL])
    assert values(page, "left_out_cited") == {MODEL: round(1 / 3, 6)}  # one chunk, in one of before.py's three answers
    assert values(page, "answers_citing_left_out") == {MODEL: round(1 / 3, 6)}
    assert values(page, "prompt_change") == {MODEL: -0.2} and values(page, "words_change") == {MODEL: -0.25}
    assert values(page, "cost_change") == {MODEL: -0.25} and values(page, "seconds_change") == {MODEL: -0.25}
    assert values(page, "asked_anyway") == {MODEL: 0.002}
    answer, refused = rows(page, "by_case")
    assert answer == {"case": "01-docs-qa/01-answer", "model": MODEL, "prompt_before": 500, "prompt_after": 400,
                      "seconds_before": 4, "seconds_after": 3, "words_before": 4, "words_after": 3,
                      "cited_before": 1.5, "cited_after": 1, "left_out": 0.5}
    assert (refused["prompt_before"], refused["prompt_after"], refused["words_after"]) == (450, None, None)


def test_agents_counts_what_each_model_tried_and_what_the_guard_refused() -> None:
    owner, injected = "04-tools/01-owner-reenables", "04-tools/03-injected-instruction"
    path = (("list_webhooks", True), ("enable_webhook", True), ("get_webhook", True))
    results = [result(case=owner, variant=None, repeat=n, steps=path, estimates=(1000, 1100, 1300, 1600),
                      checks=(("claims claims_match_actions", n != 2),)) for n in (1, 2, 3)]
    results += [result(case=injected, variant=None, steps=(("list_webhooks", True), ("delete_webhook", False)), estimates=(1000, 1200),
                       checks=(("untrusted never_attempts delete_webhook webhook=wh_31c9", False),
                               ("untrusted must_not_recommend delete_webhook", True), ("untrusted mentions_none", True)))]
    page = metrics.agents(results + [result()], [MODEL])  # 01's result is no agent's: it counts in none of these
    assert (values(page, "steps_median"), values(page, "steps_most")) == ({MODEL: 3}, {MODEL: 3})
    assert (values(page, "tried"), values(page, "refused_by_guard")) == ({MODEL: 11}, {MODEL: 1})
    # What the injected text asked for: tried once, though the guard refused it; never recommended, never repeated.
    assert [values(page, f"injected_{kind}")[MODEL] for kind in ("attempted", "recommended", "repeated")] == [1, 0, 0]
    assert values(page, "claims_mismatch") == {MODEL: 1}
    assert values(page, "inferences_median") == {MODEL: 4} and values(page, "growth_per_inference") == {MODEL: 200}
    assert rows(page, "paths") == [
        {"case": owner, "model": MODEL, "path": "list_webhooks → enable_webhook → get_webhook", "repeats": 3},
        {"case": injected, "model": MODEL, "path": "list_webhooks → delete_webhook (refused)", "repeats": 1}]


def test_an_interval_is_wide_when_few_were_graded() -> None:
    low, high = metrics.wilson(15, 18)
    assert (round(low, 2), round(high, 2)) == (0.61, 0.94)  # 83% of 18 could be 61% or 94% of many
    assert round(metrics.wilson(18, 18)[1], 6) == 1 and metrics.wilson(0, 0) is None


def test_checks_says_how_far_the_checks_tell_the_models_apart() -> None:
    steady, flips, plan = "a/steady", "b/flips", "02-account-aware/01-team-plan"
    results, calls = [], []
    for model in (steady, flips):
        for repeat in (1, 2):
            failed = model == flips and repeat == 2
            for case, variant, checked in (("01-docs-qa/01-answer", "after", (("answer answered", True), ("answer mentions_any", not failed))),
                                           (plan, None, (("conflict never_the_loser", True),))):
                name = f"{model}/{case}/{repeat}"
                results.append(result(job=name, model=model, case=case, variant=variant, repeat=repeat, checks=checked))
                calls.append(call(job=name, model=model, task=case, variant=variant, repeat=repeat, host="Two" if failed and variant else "One"))
    page = metrics.verdicts(calls, results, [steady, flips])
    number = next(one for one in page["numbers"] if one["id"] == "checks_passed")
    assert number["values"] == {steady: 1, flips: round(5 / 6, 6)} and number["n"] == {steady: 6, flips: 6}
    assert number["ranges"][flips] == [round(edge, 6) for edge in metrics.wilson(5, 6)]
    assert (values(page, "hosts"), values(page, "busiest_host_share")) == ({steady: 1, flips: 2}, {steady: 1, flips: 0.75})
    totals = {total["id"]: (total["value"], total.get("of")) for total in page["totals"]}
    # Three checks across the two cases; one of them, one model failed once. So one failure in 12, and in one case of 2.
    assert totals == {"failed": (1, 12), "always_passed": (round(2 / 3, 6), None), "cases_with_failure": (1, 2)}
    assert rows(page, "failures") == [{"check": "answer mentions_any", "failed": 1, "graded": 4, "models": "flips"}]
    assert rows(page, "disagreements") == [{"model": steady, steady: None, flips: 1}, {"model": flips, steady: 0, flips: None}]
    assert rows(page, "by_host") == [{"model": steady, "host": "One", "results": 4, "clean": 1},
                                     {"model": flips, "host": "One", "results": 3, "clean": 1},
                                     {"model": flips, "host": "Two", "results": 1, "clean": 0}]


def assembly(**given: Any) -> metrics.Assembly:
    return metrics.Assembly(**({
        "job": "j", "model": MODEL, "case": "01-docs-qa/01-answer", "variant": "after", "repeat": 1, "name": "record",
        "refused": None, "estimate": 300, "budget": 1500, "margin": 15,
        "sent": (("governance.instructions", 140), ("evidence.knowledge", 60), ("evidence.knowledge", 50), ("interaction.query", 10)),
        "left_out": (("below_threshold", "assembler", 40), ("below_threshold", "assembler", 30)), "summarized": (), "decided": (),
        "threshold": 2.0, "weakest_sent": 2.4, "strongest_left": 1.8} | given))


def test_decisions_says_what_the_assembler_did_with_what_it_was_offered() -> None:
    small = "03-budget-and-routes/02-small-route"
    committed = [assembly(model=model, repeat=repeat) for model in (MODEL, "b/other") for repeat in (1, 2)]  # one request, four times
    committed += [assembly(model=model, case=small, variant=None, name="account-help-small", estimate=820, budget=1000,
                           sent=(("governance.instructions", 300), ("interaction.history", 400), ("interaction.query", 100)),
                           left_out=(("over_budget", "assembler", 120), ("conflict_lost", "assembler", 9), ("expired", "producer", None)),
                           summarized=((55, 42), (77, 47)), decided=("policy", "moot"), threshold=None, weakest_sent=None, strongest_left=None)
                  for model in (MODEL, "b/other")]
    committed += [assembly(model=model, case="01-docs-qa/03-off-topic", refused="evidence_required", estimate=None, sent=(),
                           left_out=(("below_threshold", "assembler", 50),), weakest_sent=None, strongest_left=1.2) for model in (MODEL, "b/other")]
    # An agent's snapshots follow its own tool calls: one model looks at a webhook twice, and the second look replaces the first.
    agent = [assembly(case="04-tools/01-owner-reenables", variant=None, name=f"turn-{n}", estimate=estimate, budget=4000, left_out=left)
             for n, (estimate, left) in enumerate(((900, (("capability_not_allowed", "producer", None),)),
                                                   (1100, (("capability_not_allowed", "producer", None), ("superseded", "assembler", 70)))), start=1)]
    page = metrics.decisions(committed + agent, [MODEL, "b/other"])
    totals = {total["id"]: (total["value"], total.get("of")) for total in page["totals"]}
    # 01-03's requests are the same for every model, so each counts once: three requests, one refused.
    assert totals["refused"] == (1, 3)
    assert totals["sent"] == (7, 13)           # items sent, of those offered: 4 of 6, 3 of 6 and none of 1
    assert totals["kept_out"] == (249, None)   # by the route's tokenizer, where the snapshot holds the text: 70 + 129 + 50
    assert totals["summarized"] == (2, None) and totals["saved"] == (43, None)  # two items sent as summaries, 132 tokens as 89
    assert values(page, "assemblies") == {MODEL: 2, "b/other": None}  # 04 and 05's, where each model decides its own path
    assert values(page, "superseded") == {MODEL: 1, "b/other": None} and values(page, "not_offered") == {MODEL: 2, "b/other": None}
    assert values(page, "budget_peak") == {MODEL: 0.275, "b/other": None}
    answer, off_topic, route = rows(page, "requests")
    assert answer == {"request": "01-docs-qa/01-answer", "outcome": "sent", "offered": 6, "sent": 4, "estimate": 300, "budget": 1500,
                      "used": 0.2, "kept_out": 70, "saved": 0}
    assert (off_topic["outcome"], off_topic["sent"], off_topic["estimate"]) == ("refused: evidence_required", 0, None)
    assert (route["request"], route["saved"], route["used"]) == (f"{small} · account-help-small", 43, 0.82)
    assert rows(page, "planes")[0] == {"request": "01-docs-qa/01-answer", "governance": 140, "state": 0, "evidence": 110, "interaction": 10, "around": 40}
    reasons = {row["reason"]: row for row in rows(page, "reasons")}
    assert reasons["below_threshold"] == {"reason": "below_threshold", "stage": "assembler", "committed": 3, "tokens": 120, MODEL: 0, "b/other": 0}
    assert (reasons["superseded"]["committed"], reasons["superseded"][MODEL]) == (0, 1)
    assert rows(page, "relevance") == [{"request": "01-docs-qa/01-answer", "threshold": 2, "weakest_sent": 2.4, "strongest_left": 1.8},
                                       {"request": "01-docs-qa/03-off-topic", "threshold": 2, "weakest_sent": None, "strongest_left": 1.2}]


def test_grounding_holds_an_answer_to_the_context_it_was_sent() -> None:
    sent = ("help:a@1#0", "help:b@1#0", "help:c@1#0")  # in the payload's order: the route sends the most relevant first
    results = [result(repeat=1, sent=sent, cited=("help:a@1#0",), supported=0.9),
               result(repeat=2, sent=sent, cited=("help:b@1#0", "help:z@9#9"), supported=0.7),  # one citation was never sent
               result(repeat=3, sent=sent, cited=(), supported=0.8),
               result(variant="before", sent=(), cited=("help:a@1#0",), supported=0.5)]
    page = metrics.grounding(results, [MODEL])
    assert values(page, "words_in_context") == {MODEL: 0.8} and values(page, "words_in_context_before") == {MODEL: 0.5}
    assert values(page, "cited_of_sent") == {MODEL: round(2 / 9, 6)}   # two of the nine articles the three requests carried
    assert values(page, "citations_sent") == {MODEL: round(2 / 3, 6)}  # of three citations, two name what was sent
    assert values(page, "uncited") == {MODEL: round(1 / 3, 6)}
    assert values(page, "cited_rank") == {MODEL: 1.5}                  # the first article, and the second
    assert values(page, "cites_first") == {MODEL: 0.5}                 # of the two answers that cite, one cites the first
    assert rows(page, "by_case") == [{"case": "01-docs-qa/01-answer", "model": MODEL, "sent": 3, "cited": 1, "supported": 0.8}]


def test_agents_sets_each_path_beside_the_committed_recording_and_the_budget() -> None:
    recorded = ("list_webhooks", "get_webhook", "enable_webhook", "get_webhook")
    took = lambda *tools: tuple((tool, True) for tool in tools)
    results = [result(case="04-tools/01-owner-reenables", variant=None, repeat=1, steps=took(*recorded), recorded=recorded,
                      estimates=(1000, 1100, 1200, 1300, 1400), budget=4000),
               result(case="04-tools/01-owner-reenables", variant=None, repeat=2, steps=took("list_webhooks", "enable_webhook"), recorded=recorded,
                      estimates=(1000, 1200, 1400), budget=4000),
               result(case="05-production/owner-reenables", variant=None, steps=took("list_webhooks"), estimates=(1000, 1300), budget=4000)]
    page = metrics.agents(results, [MODEL])
    assert values(page, "recorded_path") == {MODEL: 0.5}       # of the two runs that have a recording to follow
    assert values(page, "steps_over_recorded") == {MODEL: 0.75}  # 4 of 4 and 2 of 4 tool calls
    # At 100, 200 and 300 tokens an inference, a budget of 4,000 that starts at 1,000 binds after 30, 15 and 10 more.
    assert values(page, "inferences_until_budget") == {MODEL: 15}


def test_speed_sets_each_model_as_a_card_that_opens_on_its_numbers_by_question() -> None:
    page = metrics.speed([call(ms=3000, first_token=500, generating=2800)], {"models": {MODEL: listed()}, "jobs": []})
    cards, numbers = page["cards"], [one["id"] for one in page["numbers"]]
    # The models in the order the chart draws them, each closed on a few numbers and open on every one, once each.
    assert cards["order"] == "seconds_p50" and set(cards["head"]) <= set(numbers)
    assert [group["title"] for group in cards["groups"]] == ["The wait", "The writing", "Around the call"]
    assert sorted(id for group in cards["groups"] for id in group["numbers"]) == sorted(numbers)
    # A card holds its model's share of the page's tables, which are then not set out a second time.
    assert cards["tables"] == ["seconds_by_example", "by_host"] and set(cards["tables"]) <= {table["id"] for table in page["tables"]}


def test_tokens_sets_each_model_as_a_card_and_keeps_what_belongs_to_the_requests_on_the_page() -> None:
    page = metrics.tokens([call()], [MODEL])
    cards, numbers = page["cards"], [one["id"] for one in page["numbers"]]
    assert cards["order"] == "margin_needed" and set(cards["head"]) <= set(numbers)
    assert [group["title"] for group in cards["groups"]] == ["How the host counts", "The margin", "The window"]
    assert sorted(id for group in cards["groups"] for id in group["numbers"]) == sorted(numbers)
    # The counts and margins by request move into the cards. The table of requests, whose columns are the request's
    # and not a model's, stays on the page.
    assert cards["tables"] == ["counts_by_case", "margin_by_case"]
    assert {table["id"] for table in page["tables"]} - set(cards["tables"]) == {"requests"}
    # In a card the two are one list, a request a row, since they are about the same requests in the same order.
    assert cards["merge"] == [{"title": "Each request", "columns": {"counts_by_case": "The host's count", "margin_by_case": "Margin needed"}}]
    tables = {table["id"]: table for table in page["tables"]}
    assert len({tuple(row["case"] for row in tables[id]["rows"]) for id in cards["merge"][0]["columns"]}) == 1


def test_cost_sets_each_model_as_a_card_with_the_largest_spend_first() -> None:
    page = metrics.cost([call()], [], {"models": {MODEL: listed()}, "jobs": []})
    cards, numbers = page["cards"], [one["id"] for one in page["numbers"]]
    assert (cards["order"], cards["down"]) == ("spend", True) and set(cards["head"]) <= set(numbers)
    assert [group["title"] for group in cards["groups"]] == ["What was spent", "What it bought"]
    assert sorted(id for group in cards["groups"] for id in group["numbers"]) == sorted(numbers)
    assert cards["tables"] == ["identity", "by_example"] == [table["id"] for table in page["tables"]]


CARDED = {"tokens", "cost", "speed"}


def test_every_page_with_cards_puts_each_number_in_one_group_and_names_tables_it_has(tmp_path: Path) -> None:
    name = job(tmp_path, "01-docs-qa", "01-answer/after", {"answer": "Check spam [help:sign-in@6#0].", "error": None}, ANSWER)
    called(tmp_path, name, 375)
    pages = metrics.write(tmp_path, graded(tmp_path, [name]))["pages"]
    assert {page["id"] for page in pages if page.get("cards")} == CARDED
    for page in (page for page in pages if page.get("cards")):
        cards, numbers, tables = page["cards"], [one["id"] for one in page["numbers"]], {table["id"] for table in page["tables"]}
        assert cards["order"] in numbers and set(cards["head"]) <= set(numbers), page["id"]
        assert sorted(id for group in cards["groups"] for id in group["numbers"]) == sorted(numbers), page["id"]
        assert set(cards["tables"]) <= tables, page["id"]
        # A table a card takes holds a column of models or a column per model, or it has no share to give a card.
        for id in cards["tables"]:
            columns = {column["id"] for column in next(table for table in page["tables"] if table["id"] == id)["columns"]}
            assert "model" in columns or MODEL in columns, (page["id"], id)

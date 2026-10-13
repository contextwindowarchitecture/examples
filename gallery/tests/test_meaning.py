"""What the numbers say about CWA: a fixed sentence for every number, a paragraph for every page, and a reading of
each page computed from the run."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import meaning
import metrics
from test_metrics import ANSWER, MODEL, assembly, call, called, graded, job, listed, result


def page(found: list[dict[str, Any]], id: str) -> dict[str, Any]:
    return next(one for one in found if one["id"] == id)


def test_every_number_of_a_run_says_what_it_means_for_cwa(tmp_path: Path) -> None:
    name = job(tmp_path, "01-docs-qa", "01-answer/after", {"answer": "Check spam [help:sign-in@6#0].", "error": None}, ANSWER)
    called(tmp_path, name, 375)
    written = metrics.write(tmp_path, graded(tmp_path, [name]))
    for one in written["pages"]:
        assert one["says"] and isinstance(one["reading"], list), one["id"]
        for entry in [*one["numbers"], *one.get("totals", [])]:
            assert entry.get("means"), f"{one['id']} {entry['id']} says nothing about CWA"
    # A run this small has little to read, and what it has names no missing value.
    assert not any("None" in line or "nan" in line for one in written["pages"] for line in one["reading"])
    assert set(meaning.MEANS) == {(one["id"], entry["id"]) for one in written["pages"] for entry in [*one["numbers"], *one.get("totals", [])]}


def test_the_tokens_reading_sets_the_declared_margin_against_what_each_model_needed() -> None:
    sizes = (("01-docs-qa/01-answer", 100), ("02-account-aware/01-team-plan", 200), ("03-budget-and-routes/01-large-route", 300))
    calls = [call(model=model, task=task, example=task.split("/")[0], estimate=size, prompt=int(size * rate) + added, budget=budget)
             for model, rate, added, budget in (("a/exact", 1.05, 0, 1500), ("b/adds", 1.0, 1000, 250)) for task, size in sizes]
    [tokens] = meaning.explain([metrics.tokens(calls, ["a/exact", "b/adds"])], ["a/exact", "b/adds"])
    assert tokens["reading"] == [
        "The routes declare a margin of 15%. It covered every 01–03 request for exact and none for adds.",
        "adds needed the largest margin, 1,000%; its host adds about 1,000 tokens to every request.",
        "3 calls were counted over their route's budget.input, all of them adds's.",
    ]


def test_the_checks_reading_says_whether_the_run_tells_the_models_apart() -> None:
    results = [result(model=model, repeat=repeat, checks=(("answer answered", True), ("answer mentions_any", model == "a/steady" or repeat == 1)))
               for model in ("a/steady", "b/flips") for repeat in (1, 2)]
    [checks] = meaning.explain([metrics.verdicts([], results, ["a/steady", "b/flips"])], ["a/steady", "b/flips"])
    assert checks["reading"] == [
        "1 of 8 graded checks failed, in 1 of 1 cases.",
        "answer mentions_any accounts for 1 of them.",
        "Every model's range overlaps every other's, so this run does not rank the models on its checks.",
    ]


def test_the_decisions_reading_counts_what_the_assembler_did_before_any_model_was_asked() -> None:
    made = [assembly(), assembly(case="01-docs-qa/03-off-topic", refused="evidence_required", estimate=None, sent=(),
                                 left_out=(("below_threshold", "assembler", 50),))]
    [decisions] = meaning.explain([metrics.decisions(made, [MODEL])], [MODEL])
    assert decisions["reading"][:3] == [
        "01–03's 2 requests sent 4 of the 7 items their producers offered and kept out 120 tokens.",
        "1 was refused and asked no model: 01-docs-qa/03-off-topic (evidence_required).",
        "Most of what was left out was below_threshold: 3 items.",
    ]


def test_a_reading_names_several_models_without_running_its_clauses_together() -> None:
    sizes = (("01-docs-qa/01-answer", 100), ("02-account-aware/01-team-plan", 200))
    rates = {"a/one": 1.0, "b/two": 1.0, "c/three": 3.0, "d/four": 3.0}
    calls = [call(model=model, task=task, example=task.split("/")[0], estimate=size, prompt=int(size * rate)) for model, rate in rates.items() for task, size in sizes]
    [tokens] = meaning.explain([metrics.tokens(calls, list(rates))], list(rates))
    assert tokens["reading"][0] == "The routes declare a margin of 15%. It covered every 01–03 request for one and two, and none for three and four."


def test_the_before_and_after_reading_says_which_way_the_request_changed() -> None:
    by_hand = {"variant": "before", "estimate": None, "budget": None, "margin": None, "assembly": None}
    calls = [call(model=model, **by_hand, prompt=1000) for model in ("a/smaller", "b/larger")]
    calls += [call(model="a/smaller", prompt=900), call(model="b/larger", prompt=1100)]
    results = [result(model=model, variant=variant) for model in ("a/smaller", "b/larger") for variant in ("before", "after")]
    [page] = meaning.explain([metrics.before_after(calls, results, ["a/smaller", "b/larger"])], ["a/smaller", "b/larger"])
    assert page["reading"] == ["No model cited a chunk the assembly left out.",
                               "By each model's own count, after.py's request ran from 10% smaller to 10% larger than before.py's."]


def test_a_reading_of_many_models_counts_them_rather_than_naming_each() -> None:
    models = [f"v/m{n}" for n in range(8)]
    results = [result(model=model, repeat=n, checks=(("answer answered", model == "v/m0" or n == 1),)) for model in models for n in (1, 2)]
    [page] = meaning.explain([metrics.stability(results, models)], models)
    assert page["reading"][:2] == ["m0 passed every graded case in every repeat.",
                                   "7 of the 8 models changed their result on at least one case between repeats. The request was the same to the byte each time."]
    every = [result(model=model, repeat=n, checks=(("answer answered", n == 1),)) for model in models for n in (1, 2)]
    [page] = meaning.explain([metrics.stability(every, models)], models)
    assert page["reading"][0] == "Every model changed its result on at least one case between repeats. The request was the same to the byte each time."


def test_the_speed_reading_says_what_went_wrong_in_sentences_and_names_only_who_it_happened_to() -> None:
    models = ["a/flaky", "b/steady"]
    calls = [call(model="a/flaky", attempts=2, tried=2 if n == 1 else 1, repeat=n) for n in (1, 2, 3)] + [call(model="b/steady")]
    [speed] = meaning.explain([metrics.speed(calls, {"models": {model: listed() for model in models}, "jobs": []})], models)
    assert speed["reading"] == [
        "3 of flaky's calls had to be retried after a rate limit or an outage; no other model's did.",
        "1 of flaky's calls went to a second host before one answered; no other model's did.",
        "No answer ran out of reserved output.",
    ]
    many = [f"m/{n}" for n in range(8)]
    spread = [call(model=model, tried=2) for model in many[:6] for _ in range(1 + 4 * (model == "m/0"))]
    [speed] = meaning.explain([metrics.speed(spread, {"models": {model: listed() for model in many}, "jobs": []})], many)
    # Across many models a sentence counts them, and names only the one most of it happened to.
    assert "10 calls went to a second host before one answered, across 6 of the 8 models; 5 of them 0's." in speed["reading"]
    assert "No call had to be retried." in speed["reading"]

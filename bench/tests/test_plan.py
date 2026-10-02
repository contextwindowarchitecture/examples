"""What a run would do and cost: every case of every example, for every model and repeat."""
from __future__ import annotations

from pathlib import Path

import cases
import catalog
import config
import plan

CATALOG = {"vendor/paid": catalog.Listing(input_price=2e-06, output_price=1e-05, tools=True),
           "vendor/other": catalog.Listing(input_price=1e-06, output_price=4e-06, tools=True),
           "vendor/no-tools:free": catalog.Listing(input_price=0, output_price=0, tools=False)}


def configured(*models: str, repeats: int = 1) -> config.Config:
    return config.Config(models=models, examples=config.EXAMPLES, repeats=repeats, concurrency=4, max_cost_usd=5.0,
                         confirm=True, key_env="OPENROUTER_API_KEY")


def test_every_case_runs_for_every_model_and_repeat_one_repeat_at_a_time() -> None:
    planned = plan.plan(configured("vendor/paid", "vendor/other", repeats=2), CATALOG)
    per_repeat = 2 * sum(len(cases.cases(example)) for example in config.EXAMPLES)  # both models
    assert len(planned.jobs) == 2 * per_repeat
    # A run stopped by its spending cap then holds whole repeats across every model.
    assert [job.repeat for job in planned.jobs] == [1] * per_repeat + [2] * per_repeat


def test_a_model_without_tool_support_skips_the_examples_that_send_tools() -> None:
    planned = plan.plan(configured("vendor/no-tools:free"), CATALOG)
    assert {job.case.example for job in planned.jobs} == {"01-docs-qa", "02-account-aware", "03-budget-and-routes"}
    assert planned.skipped == ["vendor/no-tools:free skips 04-tools and 05-production: OpenRouter lists no tool support"]


def test_a_job_runs_the_examples_own_command_against_the_model_and_records_in_its_folder() -> None:
    [suite] = [job for job in plan.plan(configured("vendor/paid"), CATALOG).jobs if job.case.example == "05-production"]
    assert suite.folder == Path("vendor-paid", "05-production", "evals", "1")
    assert suite.argv(Path("out")) == ["uv", "run", "evals.py", "run", "--provider", "openai", "--model", "vendor/paid",
                                       "--out", "out"]


def test_the_estimate_is_likely_calls_at_likely_sizes_and_at_most_every_budget_used_in_full() -> None:
    case = cases.Case(example="01-docs-qa", name="x", args=("after.py",), output="--record", tools=False, calls=1,
                      most_calls=1, input_tokens=1000, budget=cases.Budget(input=1500, reserved_output=16000))
    likely, most = plan.cost(plan.Job("vendor/paid", case, 1), CATALOG["vendor/paid"])
    assert round(likely, 6) == round(1000 * 2e-06 + plan.LIKELY_OUTPUT_TOKENS * 1e-05, 6)
    assert round(most, 6) == round(1500 * 2e-06 + 16000 * 1e-05, 6)

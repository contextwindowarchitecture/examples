"""Which job runs when. Jobs are stood in for by a function that waits a moment, so nothing is spawned."""
from __future__ import annotations

import threading
import time
from collections import Counter

import cases
import runner
from plan import Job

CASE = cases.Case(example="01-docs-qa", name="01-answer/after", args=("after.py",), output="--record", tools=False,
                  calls=1, most_calls=1, input_tokens=283, budget=cases.Budget(input=1500, reserved_output=16000))


def jobs(*models: str, each: int = 3) -> list[Job]:
    return [Job(model, CASE, repeat) for repeat in range(1, each + 1) for model in models]


class Jobs:
    """Stands in for running a job: notes what runs at once, and fails the jobs it is told to."""

    def __init__(self, failing: set[int] = frozenset(), cost: float = 0.0) -> None:
        self.lock = threading.Lock()
        self.running: Counter[str] = Counter()
        self.most_at_once = 0
        self.most_of_one_model: Counter[str] = Counter()
        self.ran: list[Job] = []
        self.failing, self.cost, self.spent = failing, cost, 0.0

    def __call__(self, job: Job) -> bool:
        with self.lock:
            self.running[job.model] += 1
            self.most_at_once = max(self.most_at_once, sum(self.running.values()))
            self.most_of_one_model[job.model] = max(self.most_of_one_model[job.model], self.running[job.model])
        time.sleep(0.02)
        with self.lock:
            self.running[job.model] -= 1
            self.ran.append(job)
            self.spent += self.cost
        return job.repeat not in self.failing


def test_every_job_runs_once_and_no_more_than_the_concurrency_at_a_time() -> None:
    planned, run = jobs("vendor/a", "vendor/b", "vendor/c"), Jobs()
    outcome = runner.Runner(planned, concurrency=2, free=set(), cap=10.0, spent=lambda: run.spent, execute=run).run()
    assert sorted(map(str, run.ran)) == sorted(map(str, planned)) and len(outcome.done) == len(planned)
    assert run.most_at_once == 2


def test_a_free_model_runs_one_job_at_a_time_while_paid_ones_run_beside_it() -> None:
    planned, run = jobs("vendor/a:free", "vendor/b", each=4), Jobs()
    runner.Runner(planned, concurrency=4, free={"vendor/a:free"}, cap=10.0, spent=lambda: run.spent, execute=run).run()
    assert run.most_of_one_model["vendor/a:free"] == 1
    assert run.most_of_one_model["vendor/b"] > 1


def test_no_job_starts_once_the_run_has_spent_its_cap() -> None:
    planned, run = jobs("vendor/a", each=6), Jobs(cost=1.0)
    outcome = runner.Runner(planned, concurrency=1, free=set(), cap=2.5, spent=lambda: run.spent, execute=run).run()
    assert len(run.ran) == 3  # spent 1, 2, then 3, which is past the cap
    assert outcome.not_started == planned[3:]


def test_a_failed_job_is_reported_and_the_rest_still_run() -> None:
    planned, run = jobs("vendor/a", each=3), Jobs(failing={2})
    outcome = runner.Runner(planned, concurrency=2, free=set(), cap=10.0, spent=lambda: run.spent, execute=run).run()
    assert [job.repeat for job in outcome.failed] == [2]
    assert sorted(job.repeat for job in outcome.done) == [1, 3]

"""Which job runs when. Jobs start in the plan's order, repeat by repeat, at most `concurrency` at a time. A free model
runs one job at a time, since free models share upstream rate limits; another model's job goes ahead meanwhile. No
job starts once the run has spent its cap; the jobs already running finish."""
from __future__ import annotations

import threading
from collections.abc import Callable, Collection
from dataclasses import dataclass, field

from plan import Job


@dataclass
class Outcome:
    done: list[Job] = field(default_factory=list)
    failed: list[Job] = field(default_factory=list)
    not_started: list[Job] = field(default_factory=list)  # the cap was reached first


class Runner:
    def __init__(self, jobs: list[Job], *, concurrency: int, free: Collection[str], cap: float,
                 spent: Callable[[], float], execute: Callable[[Job], bool]) -> None:
        """execute runs one job and says whether it succeeded; spent says what the run has spent so far."""
        self.jobs, self.concurrency, self.free, self.cap = jobs, concurrency, free, cap
        self.spent, self.execute = spent, execute

    def run(self) -> Outcome:
        pending = list(self.jobs)
        busy: set[str] = set()  # free models with a job running
        outcome = Outcome()
        turn = threading.Condition()

        def take() -> Job | None:
            with turn:
                while pending and self.spent() < self.cap:
                    ready = next((job for job in pending if job.model not in busy), None)
                    if ready is not None:
                        pending.remove(ready)
                        if ready.model in self.free:
                            busy.add(ready.model)
                        return ready
                    turn.wait()  # every job left is a free model's that is already running one
                return None

        def work() -> None:
            while (job := take()) is not None:
                succeeded = self.execute(job)
                with turn:
                    (outcome.done if succeeded else outcome.failed).append(job)
                    busy.discard(job.model)
                    turn.notify_all()

        workers = [threading.Thread(target=work) for _ in range(self.concurrency)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        outcome.not_started = pending
        return outcome

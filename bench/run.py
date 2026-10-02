"""Run the benchmark: the preflight, the plan and its estimate, a confirmation, then every job through the recording
proxy.

    uv run --env-file .env run.py                       # a new run, in results/<run-id>/
    uv run --env-file .env run.py --resume RUN_ID       # the jobs a run has not finished, at the commit it ran
    uv run --env-file .env run.py --config other.toml

A job runs the example's own command in the example's folder and environment, with the proxy as its OpenAI endpoint.
Its record goes to <job>/record/, what it printed to <job>/output.txt, and how it ended to <job>/job.json. A job that
failed, or did not start because the run reached its cap, runs again on --resume.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import catalog
import config
import manifest
import plan
import preflight
import proxy
from config import ROOT
from plan import Job, Plan
from runner import Runner


def environment(base_url: str, key_env: str, store: Path) -> dict[str, str]:
    """An example's environment: the proxy as its OpenAI endpoint, with a dummy key. Never the real key, nor bench's
    own VIRTUAL_ENV. 05 gets a store of its own, so its store/cwa.sqlite keeps only your runs."""
    environ = {name: value for name, value in os.environ.items() if name not in ("VIRTUAL_ENV", key_env)}
    return environ | {"OPENAI_BASE_URL": base_url, "OPENAI_API_KEY": "bench-proxy", "DOCS_QA_STORE": str(store)}


def execute(job: Job, run: Path, through: proxy.Proxy, key_env: str, progress: Progress) -> bool:
    folder = run / job.folder
    if folder.exists():
        shutil.rmtree(folder)  # an earlier attempt that failed; what it sent and spent stays in calls.jsonl
    folder.mkdir(parents=True)
    started = time.monotonic()
    with (folder / "output.txt").open("w", encoding="utf-8") as output:
        code = subprocess.run(job.argv(folder / "record"), cwd=ROOT / job.case.example, stdout=output,
                              stderr=subprocess.STDOUT,
                              env=environment(through.base_url(job.folder), key_env, folder / "store.sqlite")).returncode
    seconds = round(time.monotonic() - started, 1)
    ended = {"model": job.model, "example": job.case.example, "case": job.case.name, "repeat": job.repeat,
             "argv": job.argv(Path("record")), "exit": code, "seconds": seconds}
    (folder / "job.json").write_text(json.dumps(ended, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    progress(job, code, seconds)
    return code == 0


def finished(folder: Path) -> bool:
    path = folder / "job.json"
    return path.exists() and json.loads(path.read_text(encoding="utf-8"))["exit"] == 0


def spent_before(run: Path) -> float:
    path = run / "calls.jsonl"
    if not path.exists():
        return 0.0
    return sum(json.loads(line)["cost"] for line in path.read_text(encoding="utf-8").splitlines())


class Progress:
    """One line per job as it ends."""

    def __init__(self, total: int, through: proxy.Proxy | None = None) -> None:
        self.total, self.count, self.proxy, self.lock = total, 0, through, threading.Lock()

    def __call__(self, job: Job, code: int, seconds: float) -> None:
        with self.lock:
            self.count += 1
            spent = f"spent ${self.proxy.spent:.2f}" if self.proxy else ""
            print(f"[{self.count}/{self.total}] {'done  ' if code == 0 else f'FAIL {code}'} "
                  f"{job.folder.as_posix()}  {seconds}s  {spent}", flush=True)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=str(config.HERE / "bench.toml"), help="default: bench.toml")
    parser.add_argument("--resume", metavar="RUN_ID", help="run the jobs results/RUN_ID has not finished")
    args = parser.parse_args(argv)
    head, dirty = manifest.commit()
    if args.resume:
        run = manifest.RESULTS / args.resume
        if not (run / "manifest.json").exists():
            print(f"no run {args.resume} in {manifest.RESULTS}", file=sys.stderr)
            return 2
        recorded = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
        if recorded["repository"]["commit"] != head:
            print(f"{args.resume} ran at commit {recorded['repository']['commit'][:7]}, not {head[:7]}; "
                  "check that commit out to resume it, so one run never mixes two versions of the code", file=sys.stderr)
            return 2
        config_file, listings = run / "bench.toml", manifest.listings(recorded)
    else:
        config_file, listings = Path(args.config), catalog.fetch()
    try:
        configured = config.load(config_file)
    except config.ConfigError as error:
        print(f"{config_file}:\n  " + "\n  ".join(error.problems), file=sys.stderr)
        return 2
    listings = {model: listings[model] for model in configured.models if model in listings}

    checks = preflight.checks(configured, listings)
    print("preflight")
    for check in checks:
        print(f"  {'ok  ' if check.ok else 'FAIL'}  {check.name}: {check.detail}")
    if not all(check.ok for check in checks):
        return 1
    planned = plan.plan(configured, listings)
    if args.resume:
        if [job.folder.as_posix() for job in planned.jobs] != recorded["jobs"]:
            print(f"{args.resume}'s jobs differ from what its bench.toml plans now", file=sys.stderr)
            return 2
        jobs = [job for job in planned.jobs if not finished(run / job.folder)]
        if not jobs:
            print(f"\nNothing left to run: every job of {args.resume} has finished.")
            return 0
    else:
        jobs = planned.jobs
    plan.report(configured, Plan(jobs, planned.skipped), listings)
    if dirty:
        print("\nThe repository has uncommitted changes: the manifest says so, and the commit alone won't reproduce it.")
    if configured.confirm and not _confirmed(len(jobs)):
        print("Nothing was run.")
        return 0
    if not args.resume:
        run = manifest.RESULTS / manifest.run_id(head)
        manifest.write(run, config_file, listings, planned, head, dirty)
    print(f"\n{run}")

    with proxy.Proxy(run, os.environ[configured.key_env], spent=spent_before(run)) as through:
        progress = Progress(len(jobs), through)
        outcome = Runner(jobs, concurrency=configured.concurrency,
                         free={model for model, listing in listings.items() if listing.free},
                         cap=configured.max_cost_usd, spent=lambda: through.spent,
                         execute=lambda job: execute(job, run, through, configured.key_env, progress)).run()
        spent = through.spent
    print(f"\n{len(outcome.done)} done, {len(outcome.failed)} failed, {len(outcome.not_started)} not started; "
          f"the run has spent ${spent:.2f} of ${configured.max_cost_usd:.2f}")
    if outcome.failed or outcome.not_started:
        print(f"uv run --env-file .env run.py --resume {run.name}   # runs them again")
        return 1
    return 0


def _confirmed(jobs: int) -> bool:
    try:
        return input(f"\nRun {jobs} jobs? [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

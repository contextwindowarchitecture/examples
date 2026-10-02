"""What a run would do and what it would likely cost, before anything is sent.

    uv run plan.py                          # the preflight, then the plan and its estimate; nothing is sent
    uv run --env-file ../.env plan.py       # the same, with the key read from the repository's .env
    uv run plan.py --config other.toml

A job is one case of one example, for one model and repeat. Jobs run repeat by repeat, so a run its spending cap
stops still holds whole repeats across every model.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

import catalog
import config
import preflight
from cases import Case, cases
from catalog import Listing
from config import Config, label

# Output tokens a call likely takes: an answer with some reasoning. Reasoning models can take several times this.
LIKELY_OUTPUT_TOKENS = 1000


@dataclass(frozen=True)
class Job:
    model: str
    case: Case
    repeat: int

    @property
    def folder(self) -> Path:
        """Where its record goes, under the run's folder."""
        return Path(label(self.model), self.case.example, self.case.name, str(self.repeat))

    def argv(self, output: Path) -> list[str]:
        """The example's own command, run in the example's folder, against the model through the openai provider."""
        return ["uv", "run", *self.case.args, "--provider", "openai", "--model", self.model, self.case.output, str(output)]


@dataclass(frozen=True)
class Plan:
    jobs: list[Job]
    skipped: list[str] = field(default_factory=list)  # what a model will not run, and why


def plan(config: Config, listings: Mapping[str, Listing]) -> Plan:
    examples = {example: cases(example) for example in config.examples}
    runs: dict[str, list[str]] = {}
    skipped = []
    for model in config.models:
        if model not in listings:
            skipped.append(f"{model} skips everything: it is not on OpenRouter's model list")
            continue
        sends_tools = [example for example, found in examples.items() if any(case.tools for case in found)]
        if sends_tools and not listings[model].tools:
            skipped.append(f"{model} skips {' and '.join(sends_tools)}: OpenRouter lists no tool support")
        runs[model] = [example for example in examples if listings[model].tools or example not in sends_tools]
    jobs = [Job(model, case, repeat) for repeat in range(1, config.repeats + 1) for model in runs
            for example in runs[model] for case in examples[example]]
    return Plan(jobs, skipped)


def cost(job: Job, listing: Listing) -> tuple[float, float]:
    """Dollars, likely and at most. At most, every call sends its whole input budget and uses all its reserved output.
    The budget counts tokens with the assembler's estimate, not the model's tokenizer, so it bounds them roughly."""
    case = job.case
    likely = case.calls * (case.input_tokens * listing.input_price + LIKELY_OUTPUT_TOKENS * listing.output_price)
    most = case.most_calls * (case.budget.input * listing.input_price + case.budget.reserved_output * listing.output_price)
    return likely, most


def report(config: Config, planned: Plan, listings: Mapping[str, Listing], out: TextIO = sys.stdout) -> None:
    models = sorted({job.model for job in planned.jobs}, key=config.models.index)
    print(f"\nplan: {len(planned.jobs)} jobs, {len(models)} models x {config.repeats} repeats", file=out)
    first = [job for job in planned.jobs if job.repeat == 1 and job.model == models[0]] if models else []
    for example in dict.fromkeys(job.case.example for job in first):
        found = [job.case for job in first if job.case.example == example]
        likely, most = sum(case.calls for case in found), sum(case.most_calls for case in found)
        calls = f"{likely} calls" + (f", at most {most}" if most != likely else "")
        print(f"  {example:<22} {len(found)} case{'s' if len(found) > 1 else ''}, {calls}, per model and repeat", file=out)
    for reason in planned.skipped:
        print(f"  {reason}", file=out)
    print(f"\n  {f'estimate for {config.repeats} repeats':<40} {'likely':>9} {'at most':>9}", file=out)
    totals = [0.0, 0.0]
    for model in models:
        spent = [cost(job, listings[model]) for job in planned.jobs if job.model == model]
        likely, most = sum(pair[0] for pair in spent), sum(pair[1] for pair in spent)
        totals[0] += likely
        totals[1] += most
        free = "  free" if listings[model].free else ""
        print(f"  {model:<40} {_dollars(likely)} {_dollars(most)}{free}", file=out)
    print(f"  {'total':<40} {_dollars(totals[0])} {_dollars(totals[1])}", file=out)
    print(f"\nLikely assumes {LIKELY_OUTPUT_TOKENS:,} output tokens a call. A run starts no job once it has spent "
          f"max_cost_usd, ${config.max_cost_usd:.2f}.", file=out)


def _dollars(amount: float) -> str:
    return f"{f'${amount:.2f}':>9}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=str(config.HERE / "bench.toml"), help="default: bench.toml")
    args = parser.parse_args(argv)
    try:
        configured = config.load(Path(args.config))
    except config.ConfigError as error:
        print(f"{args.config}:\n  " + "\n  ".join(error.problems), file=sys.stderr)
        return 2
    listings = catalog.fetch()
    checks = preflight.checks(configured, listings)
    print("preflight")
    for check in checks:
        print(f"  {'ok  ' if check.ok else 'FAIL'}  {check.name}: {check.detail}")
    report(configured, plan(configured, listings), listings)
    return 0 if all(check.ok for check in checks) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

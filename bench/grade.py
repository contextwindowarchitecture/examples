"""Grade a run from its files, without a model: every recorded snapshot is assembled again, then every job's checks
are written to its checks.json, and a table by model is printed.

    uv run grade.py results/<run-id>

run.py grades a run when it ends. Grading again reads the same files and gives the same checks, so a run can be
graded after expectations.toml or the checks change.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import tomllib
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, TextIO

import checks
import preflight
from checks import Check
from config import HERE, ROOT

MEASURES = ("run", "invariant", "answer", "grounding", "conflict", "excluded", "untrusted", "actions", "refusal",
            "claims", "evals")


def replay(snapshots: list[Path], example: str = "01-docs-qa") -> dict[str, dict[str, bool]]:
    """Each snapshot assembled again in an example's environment, which has the assembler every example pins."""
    # It runs in the example's folder, so it is given absolute paths, and its answers are returned under the paths given.
    absolute = {str(path.resolve()): str(path) for path in snapshots}
    with tempfile.TemporaryDirectory() as scratch:
        listing, out = Path(scratch) / "snapshots.txt", Path(scratch) / "replayed.json"
        listing.write_text("\n".join(absolute), encoding="utf-8")
        code, said = preflight.shell(["uv", "run", "python", str(HERE / "replay.py"), str(listing), str(out)], ROOT / example)
        if code != 0:
            raise RuntimeError(f"replay failed in {example}: {said}")
        return {absolute[path]: result for path, result in json.loads(out.read_text(encoding="utf-8")).items()}


def grade(run: Path, *, replayed: dict[str, dict[str, bool]] | None = None, out: TextIO = sys.stdout) -> dict[str, list[Check]]:
    expectations = tomllib.loads((HERE / "expectations.toml").read_text(encoding="utf-8"))
    calls: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if (run / "calls.jsonl").exists():
        for line in (run / "calls.jsonl").read_text(encoding="utf-8").splitlines():
            calls[json.loads(line)["job"]].append(json.loads(line))
    if replayed is None:
        replayed = replay(sorted(run.rglob("snapshot.json")))
    graded = {}
    for path in sorted(run.rglob("job.json")):
        name = path.parent.relative_to(run).as_posix()
        graded[name] = checks.check(path.parent, calls[name], replayed, expectations)
        (path.parent / "checks.json").write_text(json.dumps({"job": name, "checks": [asdict(c) for c in graded[name]]},
                                                            indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report(graded, out)
    return graded


def report(graded: dict[str, list[Check]], out: TextIO = sys.stdout) -> None:
    """Per model and measure: checks passed of those graded. Then every failed invariant, which is a bug to look into."""
    tally: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for name, found in graded.items():
        for check in found:
            if check.passed is not None:
                counts = tally[name.split("/")[0]][check.measure]
                counts[0] += check.passed
                counts[1] += 1
    measures = [measure for measure in MEASURES if any(measure in row for row in tally.values())]
    width = max([len(model) for model in tally] + [5])
    print(f"\n  {'model':<{width}}  " + "  ".join(f"{measure:>9}" for measure in measures), file=out)
    for model, row in tally.items():
        cells = [f"{row[m][0]}/{row[m][1]}" if m in row else "" for m in measures]
        print(f"  {model:<{width}}  " + "  ".join(f"{cell:>9}" for cell in cells), file=out)
    broken = [(name, check) for name, found in graded.items() for check in found
              if check.measure == "invariant" and check.passed is False]
    for name, check in broken:
        print(f"\n  invariant {check.check} failed in {name}: {check.detail}", file=out)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run", help="a run's folder, such as results/<run-id>")
    graded = grade(Path(parser.parse_args(argv).run))
    return 0 if all(c.passed is not False for found in graded.values() for c in found if c.measure == "invariant") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

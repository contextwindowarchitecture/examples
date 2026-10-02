"""What a run was made from, written before its first job: the repository's commit and whether the tree differed from
it, the assembler each example pins, bench.toml (copied beside the manifest), the models with the prices and tool
support OpenRouter listed, and the jobs. A resume runs the same jobs at the same commit, or refuses."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from catalog import Listing
from config import HERE, ROOT, label
from plan import Plan

RESULTS = HERE / "results"


def commit() -> tuple[str, bool]:
    """The repository's commit, and whether the tree has changes it does not hold."""
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    return git("rev-parse", "HEAD"), bool(git("status", "--porcelain"))


def run_id(head: str, now: datetime | None = None) -> str:
    return f"{now or datetime.now(timezone.utc):%Y-%m-%dT%H%M%SZ}-{head[:7]}"


def write(run: Path, config_file: Path, listings: dict[str, Listing], planned: Plan, head: str,
          dirty: bool) -> dict[str, Any]:
    run.mkdir(parents=True)
    shutil.copy(config_file, run / "bench.toml")
    written = {
        "run": run.name,
        "started": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "repository": {"commit": head, "dirty": dirty},
        "assembler": [{"example": pin.example, "tag": pin.tag, "commit": pin.commit} for pin in _pins()],
        "config": {"file": "bench.toml", "sha256": hashlib.sha256(config_file.read_bytes()).hexdigest()},
        "models": {model: {"label": label(model), **asdict(listing), "free": listing.free}
                   for model, listing in listings.items()},
        "skipped": planned.skipped,
        "jobs": [job.folder.as_posix() for job in planned.jobs],
    }
    (run / "manifest.json").write_text(json.dumps(written, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return written


def listings(written: dict[str, Any]) -> dict[str, Listing]:
    """The prices and tool support a run planned with, so a resume plans the same jobs."""
    return {model: Listing(input_price=m["input_price"], output_price=m["output_price"], tools=m["tools"])
            for model, m in written["models"].items()}


def _pins() -> list[Any]:
    # scripts/assembler_pin.py reads every example's pin; like bench, it needs only the standard library.
    spec = importlib.util.spec_from_file_location("assembler_pin", ROOT / "scripts" / "assembler_pin.py")
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    # Registered before it runs: its dataclasses look their module up in sys.modules.
    sys.modules[spec.name] = module  # type: ignore[union-attr]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module.pins(ROOT)

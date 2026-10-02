"""What must hold before a run sends anything. A run records the context the repository commits, so every example's
committed scenarios must be current and every example must pin the same assembler. It needs the key, and every model
must be one OpenRouter lists."""
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from catalog import Listing
from config import ROOT, Config

# (argv, the folder to run it in) -> (exit code, what it printed)
Commands = Callable[[list[str], Path], tuple[int, str]]


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def shell(argv: list[str], cwd: Path) -> tuple[int, str]:
    # uv run sets VIRTUAL_ENV to bench's own .venv. Each example runs in its own environment, never bench's.
    environ = {name: value for name, value in os.environ.items() if name != "VIRTUAL_ENV"}
    done = subprocess.run(argv, cwd=cwd, env=environ, capture_output=True, text=True)
    return done.returncode, (done.stdout + done.stderr).strip()


def checks(config: Config, catalog: Mapping[str, Listing], environ: Mapping[str, str] = os.environ,
           commands: Commands = shell) -> list[Check]:
    found = []
    for example in config.examples:
        # 05 commits eval recordings, not scenarios, and its own suite checks them.
        if (ROOT / example / "scenarios.py").exists():
            code, said = commands(["uv", "run", "scenarios.py", "--check"], ROOT / example)
            found.append(Check(f"{example} scenarios", code == 0, _last_line(said)))
    code, said = commands([sys.executable, "scripts/assembler_pin.py"], ROOT)
    found.append(Check("assembler pin", code == 0, _last_line(said)))
    if environ.get(config.key_env):
        found.append(Check("key", True, f"{config.key_env} is set"))
    else:
        found.append(Check("key", False, f"{config.key_env} is not set; uv run --env-file .env reads it from "
                                         "bench/.env"))
    missing = [model for model in config.models if model not in catalog]
    found.append(Check("models", not missing, f"not on OpenRouter's model list: {', '.join(missing)}" if missing
                       else "every model is on OpenRouter's model list"))
    return found


def _last_line(text: str) -> str:
    return text.splitlines()[-1] if text else ""

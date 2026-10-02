"""The committed agent runs. Each folder under scenarios/ holds scenario.json, the input: who asked what, any fault to
inject, the model's replies (recorded from a live model, or scripted, as its "source" says) and every clock reading.
Replaying it runs the real loop, capability policy, guard, MCP server and assembler; only the model and the clock are
played back. The outputs are committed beside it: turn-N/snapshot.json, trace.json and payload.json for every
inference, and run.json with every tool call, the guard's decision and the answer.

    uv run scenarios.py --check    # exit 1 when a committed file differs from what a replay builds now
    uv run scenarios.py --write    # replay every scenario and rewrite its outputs, then review the diff

A replay must use every reply and every clock reading the scenario holds. When it does not, the loop has changed in a
way the recording no longer fits: record the scenario again.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import shutil
import sys
from pathlib import Path

import agent
import routes
from conversation import Conversation

SCENARIOS = Path(__file__).parent / "scenarios"


def names() -> list[str]:
    return sorted(path.parent.name for path in SCENARIOS.glob("*/scenario.json"))


def replay(name: str) -> agent.Run:
    path = SCENARIOS / name / "scenario.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    model = agent.ScriptedModel(data["model"]["source"], data["model"]["replies"])
    clock = agent.Clock(data["clock"])
    outcome = asyncio.run(agent.run(Conversation.load(path), routes.load(routes.default()), model, clock, io.StringIO()))
    unused = len(model._replies), len(clock._recorded or [])
    if unused != (0, 0):
        raise RuntimeError(f"{name}: the replay left {unused[0]} replies and {unused[1]} clock readings unused; record it again")
    return outcome


def build(name: str) -> dict[str, bytes | None]:
    return agent.files(replay(name))


def stale(name: str) -> list[str]:
    built = build(name)
    directory = SCENARIOS / name

    def current(file: str) -> bytes | None:
        return (directory / file).read_bytes() if (directory / file).exists() else None

    found = [f"{name}/{file}" for file, content in built.items() if current(file) != content]
    expected = {file for file, content in built.items() if content is not None} | {"scenario.json"}
    extra = [f"{name}/{path.relative_to(directory)}" for path in sorted(directory.rglob("*.json"))
             if str(path.relative_to(directory)) not in expected]
    return found + extra


def write(name: str) -> list[str]:
    directory = SCENARIOS / name
    for turn in directory.glob("turn-*"):
        shutil.rmtree(turn)
    agent.save(directory, replay(name))
    return [f"wrote {name}"]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        for name in names():
            for line in write(name):
                print(line)
        return 0
    differing = [file for name in names() for file in stale(name)]
    if differing:
        print("stale (run uv run scenarios.py --write, then review the diff):\n  " + "\n  ".join(differing), file=sys.stderr)
        return 1
    print(f"{len(names())} scenarios are current")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

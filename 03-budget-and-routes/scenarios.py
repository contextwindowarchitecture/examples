"""The committed scenarios. In each folder under scenarios/, conversation.json is the input, and snapshot.json,
trace.json and payload.json are what the code builds from it now, for the route the conversation names. They are committed so that a change to an article,
the instructions, the policy or the assembler pin shows up as a diff of the context someone can review.

    uv run scenarios.py --check    # exit 1 when a committed file differs from what the code builds now
    uv run scenarios.py --write    # rebuild every scenario, then read the diff before committing it

A refused scenario has no payload.json. The trace is stored without trace_id and timings, which may differ run to run
(R-23).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import context
import routes
from conversation import Conversation

SCENARIOS = Path(__file__).parent / "scenarios"


def names() -> list[str]:
    return sorted(path.parent.name for path in SCENARIOS.glob("*/conversation.json"))


def _json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def build(name: str) -> dict[str, bytes | None]:
    """Every generated file of a scenario, as bytes; None for a file that must not exist."""
    conversation = Conversation.load(SCENARIOS / name / "conversation.json")
    document = context.snapshot(conversation, routes.load(conversation.route or routes.default()))
    result = context.assemble(document)
    trace = {key: value for key, value in result.trace.items() if key not in ("trace_id", "timings")}
    return {"snapshot.json": _json(document), "trace.json": _json(trace), "payload.json": result.payload}


def stale(name: str) -> list[str]:
    """The files of a scenario that differ from what build() makes now."""
    found = []
    for file, content in build(name).items():
        path = SCENARIOS / name / file
        current = path.read_bytes() if path.exists() else None
        if current != content:
            found.append(f"{name}/{file}")
    return found


def write(name: str) -> list[str]:
    written = []
    for file, content in build(name).items():
        path = SCENARIOS / name / file
        if content is None:
            if path.exists():
                path.unlink()
                written.append(f"removed {name}/{file}")
        elif not path.exists() or path.read_bytes() != content:
            path.write_bytes(content)
            written.append(f"wrote {name}/{file}")
    return written


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

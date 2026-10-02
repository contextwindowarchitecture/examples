"""Assemble recorded snapshots again, and say whether each gives the payload and outcome recorded beside it (R-23).

    uv run python <bench>/replay.py SNAPSHOTS OUT     # in an example's folder: SNAPSHOTS lists one path a line

grade.py runs it in an example's environment, which has the assembler every example pins; the preflight checked they
pin the same one. So it imports only the assembler and the standard library, never bench's own modules.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from cwa import Snapshot, assemble


def main(listing: str, out: str) -> int:
    replayed = {}
    for line in Path(listing).read_text(encoding="utf-8").splitlines():
        snapshot = Path(line)
        result = assemble(Snapshot.from_json(json.loads(snapshot.read_text(encoding="utf-8"))))
        payload, trace = snapshot.with_name("payload.json"), json.loads(snapshot.with_name("trace.json").read_text(encoding="utf-8"))
        replayed[line] = {"payload": (payload.read_bytes() if payload.exists() else None) == result.payload,
                          "outcome": trace["result"] == result.trace["result"] and trace["refused"] == result.trace["refused"]}
    Path(out).write_text(json.dumps(replayed, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))

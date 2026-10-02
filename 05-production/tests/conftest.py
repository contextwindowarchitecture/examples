"""Shared fixtures: recorded eval runs, replayed through the real loop with their model and clock played back."""
from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import agent
import evals
import routes
from conversation import Conversation

RESULTS = sorted(path.parent for path in evals.RESULTS.glob("*/meta.json"))


def replay(folder: Path) -> agent.Run:
    """A recorded run (scenario.json), replayed: the real loop, capability policy, guard, MCP server and assembler."""
    data = json.loads((folder / "scenario.json").read_text(encoding="utf-8"))
    model = agent.ScriptedModel(data["model"]["source"], data["model"]["replies"])
    return asyncio.run(agent.run(Conversation.load(folder / "scenario.json"), routes.load(routes.default()), model,
                                 agent.Clock(data["clock"]), io.StringIO()))

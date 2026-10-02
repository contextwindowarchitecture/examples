"""Shared fixtures: recorded eval runs, replayed through the real loop with their model and clock played back."""
from __future__ import annotations

import asyncio
import io
import json
from dataclasses import replace
from pathlib import Path

import agent
import evals
import routes
from conversation import Conversation

RESULTS = sorted(path.parent for path in evals.RESULTS.glob("*/meta.json"))


def recorded_route(folder: Path) -> routes.Route:
    """The route as the recording ran it: its profile, route policy, budget, tokenizer and renderer, read from the
    first snapshot. The route's current settings may name a newer profile or model since."""
    snapshot = json.loads((folder / "turn-1" / "snapshot.json").read_text(encoding="utf-8"))
    return replace(routes.load(routes.default()), profile=snapshot["profile"], policy=snapshot["route_policy"],
                   budget=snapshot["budget"], tokenizer=snapshot["tokenizer"], renderer=snapshot["renderer"])


def replay(folder: Path) -> agent.Run:
    """A recorded run (scenario.json), replayed: the real loop, capability policy, guard, MCP server and assembler."""
    data = json.loads((folder / "scenario.json").read_text(encoding="utf-8"))
    model = agent.ScriptedModel(data["model"]["source"], data["model"]["replies"])
    return asyncio.run(agent.run(Conversation.load(folder / "scenario.json"), recorded_route(folder), model,
                                 agent.Clock(data["clock"]), io.StringIO()))

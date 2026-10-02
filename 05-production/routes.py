"""The application's model routes, from policy/routes.json. A route pairs a CWA route policy and placement profile with
the snapshot settings for one kind of model (its budget, tokenizer and renderer) and the model to send to per
provider. Choosing a route is the application's decision; everything the assembler does follows from the route's
policy, which every trace names (R-20)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

POLICY = Path(__file__).parent / "policy"


@dataclass(frozen=True)
class Route:
    name: str
    policy: dict[str, Any]   # route_policy.schema.json
    profile: dict[str, Any]  # profile.schema.json
    tokenizer: str
    renderer: str
    budget: dict[str, int]
    top_k: int
    escalate: dict[str, str]                # refusal reason -> the route to try instead
    models: dict[str, dict[str, Any]]       # provider -> model and request options

    def escalation(self, reason: str | None) -> str | None:
        return self.escalate.get(reason or "")


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def default() -> str:
    return _json(POLICY / "routes.json")["default"]


def names() -> list[str]:
    return sorted(_json(POLICY / "routes.json")["routes"])


def load(name: str) -> Route:
    config = _json(POLICY / "routes.json")["routes"][name]
    return Route(
        name=name, policy=_json(POLICY / config["policy"]), profile=_json(POLICY / config["profile"]),
        tokenizer=config["tokenizer"], renderer=config["renderer"], budget=config["budget"],
        top_k=config["retrieval"]["top_k"], escalate=config["escalate"], models=config["models"],
    )

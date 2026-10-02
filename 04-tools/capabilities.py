"""The capability policy and the guard: what the model may be offered, and what it may actually call.

offer() is the capability-policy producer. The server proposes tools; the policy grants the ones policy/capabilities.json
allows for the user's role, with the policy's own description and a pinned schema, and reports every other proposal as
capability_not_allowed. The snapshot's grant names the offered ids, so no other producer can add a tool (R-15).

authorize() is the guard. It runs on every tool call the model makes, before the server sees it: the tool must have
been offered on this inference, the arguments must match its schema, and the arguments that name a workspace must
name the signed-in one. The model's wording plays no part; only the call and the application's own state do (R-5).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

POLICY = Path(__file__).parent / "policy" / "capabilities.json"


@dataclass(frozen=True)
class Grant:
    tool: str
    cap_id: str
    input_schema: dict[str, Any]
    scope: dict[str, str]  # argument -> the request scope key it must equal


@dataclass(frozen=True)
class Decision:
    approved: bool
    reason: str


def _policy() -> dict[str, Any]:
    return json.loads(POLICY.read_text(encoding="utf-8"))


def schema_sha256(schema: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def offer(proposed: list[dict[str, Any]], role: str, now: str, *, final_turn: bool = False
          ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Grant]]:
    """The capability-policy batch, the snapshot's grant, and the grants by tool name, for one inference. On the final
    turn nothing is offered, so the model has to answer with what it has."""
    policy = _policy()
    items, excluded, granted = [], [], {}
    for tool in [] if final_turn else sorted(proposed, key=lambda proposal: proposal["name"]):
        name, cap_id = tool["name"], f"cap:{tool['name']}"
        rule = policy["grants"].get(name)
        if rule is None or role not in rule["roles"] or rule["schema_sha256"] != schema_sha256(tool["input_schema"]):
            # Never granted, not for this role, or the server changed the tool since the policy pinned it.
            excluded.append({"item_id": cap_id, "reason": "capability_not_allowed", "stage": "producer"})
            continue
        granted[name] = Grant(name, cap_id, tool["input_schema"], rule["scope"])
        items.append({
            "id": cap_id, "slot": "governance.capabilities", "source": f"capability-policy:{policy['server']}/{name}",
            "source_version": policy["allow_list_version"], "authority": "governing", "trust": "verified",
            "freshness": now, "token_budget": None, "variants": [], "conflict_policy": "governs", "lineage": "verbatim",
            "eligibility": "route-policy", "injection_risk": "none",
            # The tools channel entry: the policy's description, the schema the policy pinned.
            "body": json.dumps({"name": name, "description": rule["description"], "input_schema": tool["input_schema"]},
                               sort_keys=True),
        })
    batch = {"producer": {"id": policy["policy_producer"], "kind": "capability_policy"}, "items": items, "excluded": excluded}
    grant = {"policy_producer": policy["policy_producer"], "allow_list_version": policy["allow_list_version"],
             "allowed_ids": sorted(item["id"] for item in items)}
    return batch, grant, granted


def authorize(name: str, arguments: Any, granted: dict[str, Grant], scope: dict[str, str]) -> Decision:
    """Approve or deny one tool call the model asked for."""
    if name not in granted:
        never = _policy()["never"]
        why = f": {never[name]}" if name in never else ""
        return Decision(False, f"{name} is not offered on this route{why}")
    grant = granted[name]
    if not isinstance(arguments, dict):
        return Decision(False, f"the arguments for {name} are not a JSON object")
    problems = [error.message for error in jsonschema.Draft202012Validator(grant.input_schema).iter_errors(arguments)]
    if problems:
        return Decision(False, f"the arguments do not match {name}'s schema: {'; '.join(sorted(problems))}")
    for argument, key in grant.scope.items():
        if arguments.get(argument) != scope[key]:
            return Decision(False, f"{argument}={arguments.get(argument)!r} is not the signed-in {argument} ({scope[key]})")
    return Decision(True, f"offered as {grant.cap_id}; arguments match the schema and the request's scope")

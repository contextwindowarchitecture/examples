"""A deployment runs only pinned policy, an evaluated profile, and the model that profile was evaluated for (R-19, R-20)."""
from __future__ import annotations

import copy
from dataclasses import replace

import pytest
from cwa.registry import RegistryError

import agent
import routes

EVALUATION = {"status": "evaluated", "suite": "fernway-agent-evals/v1", "date": "2026-10-02",
              "result": "6 of 6 cases passed", "artifact": "evals/results/x/report.json"}


def model() -> str:
    """The model the route's profile names: the only one it can deploy with."""
    return routes.load(routes.default()).profile["model_family"]


def route(evaluated: bool) -> routes.Route:
    loaded = routes.load(routes.default())
    if not evaluated:
        return loaded
    return replace(loaded, profile={**loaded.profile, "evaluation": EVALUATION})


def test_an_unevaluated_profile_is_not_deployable() -> None:
    with pytest.raises(RegistryError, match="unevaluated"):
        agent.deployable(route(evaluated=False), model())


def test_an_evaluated_profile_deploys_for_its_model() -> None:
    deployed = agent.deployable(route(evaluated=True), model())
    assert deployed.profile["evaluation"]["status"] == "evaluated"


def test_an_evaluated_profile_does_not_deploy_for_another_model() -> None:
    with pytest.raises(RegistryError, match=f"evaluated for {model()}, not another-model"):
        agent.deployable(route(evaluated=True), "another-model")


def test_a_profile_changed_without_a_new_version_is_refused() -> None:
    changed = route(evaluated=True)
    profile = copy.deepcopy(changed.profile)
    profile["placement"] = list(reversed(profile["placement"][2:])) + profile["placement"][:2]
    with pytest.raises(RegistryError, match="without a version increase"):
        agent.deployable(replace(changed, profile=profile), model())


def test_a_route_policy_changed_without_a_new_version_is_refused() -> None:
    changed = route(evaluated=True)
    policy = copy.deepcopy(changed.policy)
    policy["slots"]["evidence.knowledge"]["min_relevance"] = 1.0
    with pytest.raises(RegistryError, match="without a version increase"):
        agent.deployable(replace(changed, policy=policy), model())

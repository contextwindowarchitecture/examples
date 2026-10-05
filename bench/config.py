"""bench.toml: the models to run and how. It is checked before anything runs, and every problem is reported at once.

    models = ["vendor/model", ...]     # required: OpenRouter model IDs, sent as written

    [openrouter]
    key_env = "OPENROUTER_API_KEY"     # the variable that holds the key, never the key itself

    [run]
    examples = [...]                   # default: all five, always run in their own order
    repeats = 1                        # runs of each case per model
    concurrency = 4                    # cases at a time; free models run one call at a time
    max_cost_usd = 15.0                # required: no case starts once the run has spent this
    confirm = true                     # show the plan and its estimate, and wait for a yes
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # the repository, whose numbered folders are the examples
EXAMPLES = ("01-docs-qa", "02-account-aware", "03-budget-and-routes", "04-tools", "05-production")
# 01-03 send every model the same snapshots (the same_context invariant): what differs between models there is the
# model's or its host's. In 04 and 05 each model's tool calls decide what its next snapshot holds.
SAME_CONTEXT = ("01-docs-qa", "02-account-aware", "03-budget-and-routes")
SETTINGS = {"": {"models", "openrouter", "run"}, "openrouter": {"key_env"},
            "run": {"examples", "repeats", "concurrency", "max_cost_usd", "confirm"}}


class ConfigError(ValueError):
    """bench.toml cannot be run as written."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Config:
    models: tuple[str, ...]
    examples: tuple[str, ...]
    repeats: int
    concurrency: int
    max_cost_usd: float
    confirm: bool
    key_env: str


def label(model: str) -> str:
    """A model's folder name: its ID with / and : replaced, as in google-gemma-4-31b-it-free."""
    return re.sub(r"[/:]", "-", model)


def moving(model: str) -> str | None:
    """Why an ID names no fixed model, or None. What answers behind it changes, so runs could not be compared."""
    if model.startswith("~"):
        return "OpenRouter's alias for the latest model in a family"
    if model.startswith("openrouter/"):
        return "an OpenRouter router, which picks a model per request"
    return None


def load(path: Path) -> Config:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    run, openrouter = data.get("run", {}), data.get("openrouter", {})
    problems: list[str] = []

    models = data.get("models")
    if not (isinstance(models, list) and models and all(isinstance(model, str) and model for model in models)):
        problems.append("models must be a list of OpenRouter model IDs")
        models = []
    problems += [f"{model} is listed twice" for model in sorted({m for m in models if models.count(m) > 1})]
    problems += [f"{model} is {why}: name a fixed model" for model in models if (why := moving(model))]
    labels = [label(model) for model in dict.fromkeys(models)]
    problems += [f"two models share the folder {name}" for name in sorted({n for n in labels if labels.count(n) > 1})]

    examples = run.get("examples", list(EXAMPLES))
    unknown = [name for name in examples if name not in EXAMPLES] if isinstance(examples, list) else [str(examples)]
    problems += [f"run.examples: {name} is not an example; the examples are {', '.join(EXAMPLES)}" for name in unknown]

    repeats = _whole(run, "repeats", 1, problems)
    concurrency = _whole(run, "concurrency", 4, problems)
    cap = run.get("max_cost_usd")
    if cap is None:
        problems.append("run.max_cost_usd is required: a run spends money")
    elif isinstance(cap, bool) or not isinstance(cap, int | float) or cap <= 0:
        problems.append("run.max_cost_usd must be a number of dollars above 0")
    confirm = run.get("confirm", True)
    if not isinstance(confirm, bool):
        problems.append("run.confirm must be true or false")
    key_env = openrouter.get("key_env", "OPENROUTER_API_KEY")
    if not (isinstance(key_env, str) and key_env):
        problems.append("openrouter.key_env must name an environment variable")

    for table, allowed in SETTINGS.items():
        values = data if not table else data.get(table, {})
        problems += [f"{table + '.' if table else ''}{key} is not a setting" for key in values if key not in allowed]
    if problems:
        raise ConfigError(problems)
    return Config(models=tuple(models), examples=tuple(name for name in EXAMPLES if name in examples), repeats=repeats,
                  concurrency=concurrency, max_cost_usd=float(cap), confirm=confirm, key_env=key_env)


def _whole(table: dict[str, Any], key: str, default: int, problems: list[str]) -> int:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        problems.append(f"run.{key} must be a whole number of at least 1")
        return default
    return value

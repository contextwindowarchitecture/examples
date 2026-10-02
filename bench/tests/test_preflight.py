"""What must hold before a run sends anything. The commands are recorded, not run."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import catalog
import config
import preflight

CONFIG = config.Config(models=("vendor/paid",), examples=config.EXAMPLES, repeats=1, concurrency=4, max_cost_usd=5.0,
                       confirm=True, key_env="OPENROUTER_API_KEY")
CATALOG = {"vendor/paid": catalog.Listing(input_price=2e-06, output_price=1e-05, tools=True)}
KEY = {"OPENROUTER_API_KEY": "sk-or-secret"}


class Commands:
    """Stands in for the shell: records each command and where it ran, and answers with a fixed exit code."""

    def __init__(self, failing: str | None = None) -> None:
        self.ran: list[tuple[str, str]] = []
        self.failing = failing

    def __call__(self, argv: list[str], cwd: Path) -> tuple[int, str]:
        self.ran.append((" ".join(argv[1:]), cwd.name))  # without the program: uv, or this Python
        failed = self.failing == cwd.name
        return (1, "scenarios/01-answer/payload.json is stale") if failed else (0, "all current")


def failures(found: list[preflight.Check]) -> dict[str, str]:
    return {check.name: check.detail for check in found if not check.ok}


def test_the_scenarios_of_every_example_that_has_them_and_the_assembler_pin_are_checked() -> None:
    commands = Commands()
    found = preflight.checks(CONFIG, CATALOG, KEY, commands)
    # 05 commits eval recordings, not scenarios, and its own suite checks them.
    assert commands.ran == [("run scenarios.py --check", "01-docs-qa"), ("run scenarios.py --check", "02-account-aware"),
                            ("run scenarios.py --check", "03-budget-and-routes"), ("run scenarios.py --check", "04-tools"),
                            ("scripts/assembler_pin.py", config.ROOT.name)]
    assert failures(found) == {}


def test_a_stale_scenario_fails_with_what_the_check_said() -> None:
    found = preflight.checks(CONFIG, CATALOG, KEY, Commands(failing="02-account-aware"))
    assert failures(found) == {"02-account-aware scenarios": "scenarios/01-answer/payload.json is stale"}


def test_a_missing_key_fails_and_a_present_one_is_never_shown() -> None:
    assert failures(preflight.checks(CONFIG, CATALOG, {}, Commands())) == {
        "key": "OPENROUTER_API_KEY is not set; uv run --env-file ../.env reads it from the repository's .env"}
    assert all("sk-or-secret" not in check.detail for check in preflight.checks(CONFIG, CATALOG, KEY, Commands()))


def test_a_model_openrouter_does_not_list_fails() -> None:
    unknown = config.Config(**{**CONFIG.__dict__, "models": ("vendor/paid", "vendor/typo")})
    assert failures(preflight.checks(unknown, CATALOG, KEY, Commands())) == {
        "models": "not on OpenRouter's model list: vendor/typo"}


def test_an_example_runs_without_benchs_own_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # uv run sets VIRTUAL_ENV to bench's .venv. Each example has its own, and uv warns about the one it was handed.
    monkeypatch.setenv("VIRTUAL_ENV", str(config.HERE / ".venv"))
    code, said = preflight.shell([sys.executable, "-c", "import os; print(os.environ.get('VIRTUAL_ENV'))"], tmp_path)
    assert (code, said) == (0, "None")

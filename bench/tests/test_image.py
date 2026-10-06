"""The viewer's image: what its build context may hold. bench/.env holds the key, so the context is an allowlist."""
from __future__ import annotations

from config import HERE


def test_the_build_context_holds_the_server_the_viewer_and_the_results_only() -> None:
    lines = [line.strip() for line in (HERE / ".containerignore").read_text().splitlines()]
    rules = [line for line in lines if line and not line.startswith("#")]
    assert rules[0] == "*"  # everything is left out first
    assert {rule for rule in rules if rule.startswith("!")} == {"!serve.py", "!config.py", "!viewer", "!results"}

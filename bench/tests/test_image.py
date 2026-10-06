"""The viewer's image: what its build context may hold. bench/.env holds the key, so the context is an allowlist."""
from __future__ import annotations

from config import HERE


def test_the_build_context_holds_the_server_the_viewer_and_the_results_only() -> None:
    lines = [line.strip() for line in (HERE / ".containerignore").read_text().splitlines()]
    rules = [line for line in lines if line and not line.startswith("#")]
    assert rules[0] == "*"  # everything is left out first
    assert {rule for rule in rules if rule.startswith("!")} == {"!serve.py", "!config.py", "!viewer", "!results"}


def test_env_files_are_left_out_by_name_after_every_allowed_path() -> None:
    # As in .gitignore. Ignore files apply the last rule that matches, so nothing allowed above can bring a key back.
    lines = [line.strip() for line in (HERE / ".containerignore").read_text().splitlines()]
    rules = [line for line in lines if line and not line.startswith("#")]
    last_allowed = max(i for i, rule in enumerate(rules) if rule.startswith("!"))
    assert {".env", "**/.env"} <= set(rules[last_allowed + 1:])


def test_the_pull_secret_overlay_keeps_its_credentials_out_of_git() -> None:
    # openshift/pull-secret/, a kustomize component, builds the pull secret from auth.json, a login that stays local.
    overlay = HERE / "openshift" / "pull-secret"
    assert "auth.json" in (overlay / ".gitignore").read_text().split()
    assert "auth.json" in (overlay / "kustomization.yaml").read_text()

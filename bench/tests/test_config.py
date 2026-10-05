"""bench.toml: what a run needs, checked before anything runs, with every problem reported at once."""
from __future__ import annotations

from pathlib import Path

import pytest

import config

VALID = '''
models = ["vendor/model-a", "vendor/model-b:free"]

[run]
max_cost_usd = 5.0
'''


def load(tmp_path: Path, text: str) -> config.Config:
    path = tmp_path / "bench.toml"
    path.write_text(text, encoding="utf-8")
    return config.load(path)


def problems(tmp_path: Path, text: str) -> list[str]:
    with pytest.raises(config.ConfigError) as raised:
        load(tmp_path, text)
    return raised.value.problems


def test_the_committed_configuration_loads() -> None:
    loaded = config.load(config.HERE / "bench.toml")
    assert len(loaded.models) == 14
    assert loaded.examples == config.EXAMPLES
    assert (loaded.repeats, loaded.max_cost_usd, loaded.key_env) == (10, 30.0, "OPENROUTER_API_KEY")


def test_only_models_and_a_spending_cap_are_required(tmp_path: Path) -> None:
    loaded = load(tmp_path, VALID)
    assert loaded.models == ("vendor/model-a", "vendor/model-b:free")
    assert (loaded.examples, loaded.repeats, loaded.concurrency, loaded.confirm) == (config.EXAMPLES, 1, 4, True)


@pytest.mark.parametrize("model, why", [("~vendor/model-latest", "alias"), ("openrouter/free", "router")])
def test_a_model_that_is_a_moving_target_is_refused(tmp_path: Path, model: str, why: str) -> None:
    [problem] = problems(tmp_path, VALID.replace('"vendor/model-a"', f'"{model}"'))
    assert model in problem and why in problem


def test_a_run_without_a_spending_cap_is_refused(tmp_path: Path) -> None:
    assert problems(tmp_path, 'models = ["vendor/model-a"]') == ["run.max_cost_usd is required: a run spends money"]


def test_every_problem_is_reported_at_once(tmp_path: Path) -> None:
    found = problems(tmp_path, '''
models = ["vendor/model-a", "vendor/model-a"]

[run]
examples = ["06-unknown"]
repeats = 0
repeat = 3
max_cost_usd = 5.0
''')
    assert found == ["vendor/model-a is listed twice",
                     "run.examples: 06-unknown is not an example; the examples are " + ", ".join(config.EXAMPLES),
                     "run.repeats must be a whole number of at least 1",
                     "run.repeat is not a setting"]


def test_the_examples_run_in_their_own_order(tmp_path: Path) -> None:
    loaded = load(tmp_path, VALID + 'examples = ["04-tools", "01-docs-qa"]\n')
    assert loaded.examples == ("01-docs-qa", "04-tools")


def test_a_models_folder_is_its_id_without_slashes_or_colons() -> None:
    assert config.label("google/gemma-4-31b-it:free") == "google-gemma-4-31b-it-free"

"""Each route reaches its own endpoint: an escalation can move one request from a local server to a hosted one."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import openai
import pytest

import providers
import routes


@pytest.fixture
def made(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace the OpenAI client with one that records how it was built and what it was asked."""
    record: dict[str, Any] = {}

    class Client:
        def __init__(self, **settings: Any) -> None:
            record["settings"] = settings
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **request: Any) -> Any:
            record["request"] = request
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))])

    monkeypatch.setattr(openai, "OpenAI", Client)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "local-key")
    monkeypatch.setenv("GROQ_API_KEY", "hosted-key")
    return record


def ask(route: str) -> str:
    options = routes.load(route).models["openai"]
    return providers.ask("openai", options, ["instructions"], [{"role": "user", "content": "question"}], 100)


def test_the_large_route_names_its_own_endpoint_and_key(made: dict[str, Any]) -> None:
    assert ask("account-help") == "answer"
    assert made["settings"] == {"base_url": "https://api.groq.com/openai/v1", "api_key": "hosted-key"}
    assert made["request"]["model"] == "openai/gpt-oss-120b"
    assert not {"base_url", "api_key_env"} & set(made["request"]), "endpoint settings are not request parameters"


def test_the_small_route_uses_the_environments_endpoint(made: dict[str, Any]) -> None:
    assert ask("account-help-small") == "answer"
    assert made["settings"] == {"base_url": "http://127.0.0.1:8000/v1", "api_key": "local-key"}
    assert made["request"]["model"] == "gpt-oss-20b-MXFP4-Q8"


def test_asking_does_not_change_the_routes_options(made: dict[str, Any]) -> None:
    options = routes.load("account-help").models["openai"]
    before = dict(options)
    providers.ask("openai", options, [], [{"role": "user", "content": "question"}], 100)
    assert options == before

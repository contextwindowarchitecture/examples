"""Send a request to a model through the provider's official SDK. The agent hands chat() the system text, the tools
and the messages from the assembled payload, unchanged, and the route's model and request options for the provider.
The reply comes back in one shape whichever SDK made it: text, and the tool calls the model asked for.

    anthropic   the Claude API, through the anthropic SDK: ANTHROPIC_API_KEY, or an `ant auth login` profile
    openai      OpenAI, or any OpenAI-compatible server such as a local model, through the openai SDK:
                OPENAI_API_KEY, and OPENAI_BASE_URL for a local server
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


class ProviderError(RuntimeError):
    """The model could not be asked, or declined to answer."""


@dataclass(frozen=True)
class Call:
    name: str
    arguments: Any  # parsed JSON, never string-matched; None when the model sent arguments that are not JSON


@dataclass(frozen=True)
class Reply:
    text: str
    calls: list[Call] = field(default_factory=list)


def chat(provider: str, options: dict[str, Any], system: list[str], tools: list[dict[str, Any]],
         messages: list[dict[str, str]], max_tokens: int) -> Reply:
    """tools are tool specifications, {"name", "description", "input_schema"}, as the capability policy wrote them."""
    if provider == "anthropic":
        return _anthropic(options, system, tools, messages, max_tokens)
    if provider == "openai":
        return _openai(options, system, tools, messages, max_tokens)
    raise ProviderError(f"unknown provider {provider!r}")


def ask(provider: str, options: dict[str, Any], system: list[str], messages: list[dict[str, str]], max_tokens: int) -> str:
    """A request without tools, for text only."""
    return chat(provider, options, system, [], messages, max_tokens).text


def _anthropic(options: dict[str, Any], system: list[str], tools: list[dict[str, Any]], messages: list[dict[str, str]],
               max_tokens: int) -> Reply:
    import anthropic

    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            max_tokens=max_tokens,
            system=[{"type": "text", "text": text} for text in system],
            messages=messages,
            **({"tools": tools} if tools else {}),
            **options,  # the route's model, and its effort and refusal fallbacks
        )
    except anthropic.AuthenticationError as error:
        raise ProviderError("no Claude API credentials: set ANTHROPIC_API_KEY or run `ant auth login`") from error
    except anthropic.NotFoundError as error:
        raise ProviderError(f"the Claude API does not know model {options.get('model')!r}") from error
    except anthropic.RateLimitError as error:
        raise ProviderError("rate limited by the Claude API; try again shortly") from error
    except anthropic.APIStatusError as error:
        raise ProviderError(f"the Claude API answered {error.status_code}: {error.message}") from error
    except anthropic.APIConnectionError as error:
        raise ProviderError(f"cannot reach the Claude API: {error}") from error
    if response.stop_reason == "refusal":
        raise ProviderError("the model declined to answer")
    text = "".join(block.text for block in response.content if block.type == "text")
    calls = [Call(block.name, block.input) for block in response.content if block.type == "tool_use"]
    return Reply(text, calls)


def _openai(options: dict[str, Any], system: list[str], tools: list[dict[str, Any]], messages: list[dict[str, str]],
            max_tokens: int) -> Reply:
    import openai

    # A route may name its own OpenAI-compatible endpoint, and the environment variable that holds its key, so one
    # escalation can go from a local server to a hosted one. Otherwise OPENAI_BASE_URL and OPENAI_API_KEY apply.
    options = dict(options)
    base_url = options.pop("base_url", None) or os.environ.get("OPENAI_BASE_URL")
    key_variable = options.pop("api_key_env", "OPENAI_API_KEY")
    # A local server usually checks no key, but the SDK insists on one.
    client = openai.OpenAI(base_url=base_url, api_key=os.environ.get(key_variable) or "local")
    # Chat completions takes one system message; some local servers honor only the first.
    request = ([{"role": "system", "content": "\n\n".join(system)}] if system else []) + messages
    functions = [{"type": "function", "function": {"name": tool["name"], "description": tool["description"],
                                                   "parameters": tool["input_schema"]}} for tool in tools]
    # OpenAI's reasoning models reject max_tokens; many local servers know only max_tokens.
    limit = {"max_tokens": max_tokens} if base_url else {"max_completion_tokens": max_tokens}
    model = options.get("model")
    try:
        completion = client.chat.completions.create(messages=request, **({"tools": functions} if functions else {}),
                                                    **limit, **options)
    except openai.AuthenticationError as error:
        raise ProviderError(f"{base_url or 'OpenAI'} rejected the key: set {key_variable}") from error
    except openai.NotFoundError as error:
        raise ProviderError(f"{base_url or 'OpenAI'} does not know model {model!r}") from error
    except openai.APIStatusError as error:
        raise ProviderError(f"{base_url or 'OpenAI'} answered {error.status_code}: {error.message}") from error
    except openai.APIConnectionError as error:
        raise ProviderError(f"cannot reach {base_url or 'OpenAI'}: {error}") from error
    message = completion.choices[0].message
    return Reply(message.content or "", [Call(call.function.name, _json(call.function.arguments)) for call in message.tool_calls or []])


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None

"""Send a request to a model through the provider's official SDK. The app hands ask() the system text and the messages
from the assembled payload, unchanged, and the route's model and request options for the provider.

    anthropic   the Claude API, through the anthropic SDK: ANTHROPIC_API_KEY, or an `ant auth login` profile
    openai      OpenAI, or any OpenAI-compatible server such as a local model, through the openai SDK:
                OPENAI_API_KEY, and OPENAI_BASE_URL for a local server
"""
from __future__ import annotations

import os
from typing import Any


class ProviderError(RuntimeError):
    """The model could not be asked, or declined to answer."""


def ask(provider: str, options: dict[str, Any], system: list[str], messages: list[dict[str, str]], max_tokens: int) -> str:
    """options holds "model" and any other request parameters the route sets for this provider."""
    if provider == "anthropic":
        return _anthropic(options, system, messages, max_tokens)
    if provider == "openai":
        return _openai(options, system, messages, max_tokens)
    raise ProviderError(f"unknown provider {provider!r}")


def _anthropic(options: dict[str, Any], system: list[str], messages: list[dict[str, str]], max_tokens: int) -> str:
    import anthropic

    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            max_tokens=max_tokens,
            system=[{"type": "text", "text": text} for text in system],
            messages=messages,
            **options,  # the route's model, and for the large route its effort and refusal fallbacks
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
    return "".join(block.text for block in response.content if block.type == "text")


def _openai(options: dict[str, Any], system: list[str], messages: list[dict[str, str]], max_tokens: int) -> str:
    import openai

    base_url = os.environ.get("OPENAI_BASE_URL")
    # A local server usually checks no key, but the SDK insists on one.
    client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY") or "local")
    # Chat completions takes one system message; some local servers honor only the first.
    request = ([{"role": "system", "content": "\n\n".join(system)}] if system else []) + messages
    # OpenAI's reasoning models reject max_tokens; many local servers know only max_tokens.
    limit = {"max_tokens": max_tokens} if base_url else {"max_completion_tokens": max_tokens}
    model = options.get("model")
    try:
        completion = client.chat.completions.create(messages=request, **limit, **options)
    except openai.AuthenticationError as error:
        raise ProviderError("no OpenAI credentials: set OPENAI_API_KEY") from error
    except openai.NotFoundError as error:
        raise ProviderError(f"{base_url or 'OpenAI'} does not know model {model!r}") from error
    except openai.APIStatusError as error:
        raise ProviderError(f"{base_url or 'OpenAI'} answered {error.status_code}: {error.message}") from error
    except openai.APIConnectionError as error:
        raise ProviderError(f"cannot reach {base_url or 'OpenAI'}: {error}") from error
    return completion.choices[0].message.content or ""

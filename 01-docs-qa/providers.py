"""Send a request to a model through the provider's official SDK. Both apps hand ask() the same two things: the system
text and the messages. before.py builds them by hand; after.py takes them from the assembled payload unchanged.

    anthropic   the Claude API, through the anthropic SDK: ANTHROPIC_API_KEY, or an `ant auth login` profile
    openai      OpenAI, or any OpenAI-compatible server such as a local model, through the openai SDK:
                OPENAI_API_KEY, OPENAI_BASE_URL (for a local server), and DOCS_QA_MODEL or --model
"""
from __future__ import annotations

import os

ANTHROPIC_MODEL = "claude-opus-5-5"


class ProviderError(RuntimeError):
    """The model could not be asked, or declined to answer."""


def ask(provider: str, model: str | None, system: list[str], messages: list[dict[str, str]], max_tokens: int) -> str:
    if provider == "anthropic":
        return _anthropic(model or ANTHROPIC_MODEL, system, messages, max_tokens)
    if provider == "openai":
        if not model:
            raise ProviderError("the openai provider needs a model: pass --model or set DOCS_QA_MODEL")
        return _openai(model, system, messages, max_tokens)
    raise ProviderError(f"unknown provider {provider!r}")


def _anthropic(model: str, system: list[str], messages: list[dict[str, str]], max_tokens: int) -> str:
    import anthropic

    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": text} for text in system],
            messages=messages,
            # A help-center chat route: low effort answers these well and keeps latency and cost down.
            output_config={"effort": "low"},
            # If a safety classifier declines, the API re-runs the request on a fallback model it chooses.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as error:
        raise ProviderError("no Claude API credentials: set ANTHROPIC_API_KEY or run `ant auth login`") from error
    except anthropic.NotFoundError as error:
        raise ProviderError(f"the Claude API does not know model {model!r}") from error
    except anthropic.RateLimitError as error:
        raise ProviderError("rate limited by the Claude API; try again shortly") from error
    except anthropic.APIStatusError as error:
        raise ProviderError(f"the Claude API answered {error.status_code}: {error.message}") from error
    except anthropic.APIConnectionError as error:
        raise ProviderError(f"cannot reach the Claude API: {error}") from error
    if response.stop_reason == "refusal":
        raise ProviderError("the model declined to answer")
    return "".join(block.text for block in response.content if block.type == "text")


def _openai(model: str, system: list[str], messages: list[dict[str, str]], max_tokens: int) -> str:
    import openai

    base_url = os.environ.get("OPENAI_BASE_URL")
    # A local server usually checks no key, but the SDK insists on one.
    client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY") or "local")
    # Chat completions takes one system message; some local servers honor only the first.
    request = ([{"role": "system", "content": "\n\n".join(system)}] if system else []) + messages
    # OpenAI's reasoning models reject max_tokens; many local servers know only max_tokens.
    limit = {"max_tokens": max_tokens} if base_url else {"max_completion_tokens": max_tokens}
    try:
        completion = client.chat.completions.create(model=model, messages=request, **limit)
    except openai.AuthenticationError as error:
        raise ProviderError("no OpenAI credentials: set OPENAI_API_KEY") from error
    except openai.NotFoundError as error:
        raise ProviderError(f"{base_url or 'OpenAI'} does not know model {model!r}") from error
    except openai.APIStatusError as error:
        raise ProviderError(f"{base_url or 'OpenAI'} answered {error.status_code}: {error.message}") from error
    except openai.APIConnectionError as error:
        raise ProviderError(f"cannot reach {base_url or 'OpenAI'}: {error}") from error
    return completion.choices[0].message.content or ""

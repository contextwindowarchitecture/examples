"""The help-center bot as it is usually written: retrieve, paste the chunks into the system prompt, keep the last few
messages, send. It works. What it cannot tell you is what it sent, what it left out, and why.
Compare build_request() with the one in after.py.

    uv run before.py "How do I export all my projects?"                          # prints the request it would send
    uv run before.py --conversation scenarios/02-long-conversation/conversation.json
    uv run --env-file .env before.py --provider anthropic "How do I export all my projects?"
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

import cli
import corpus
import providers
from conversation import Conversation

INSTRUCTIONS = Path(__file__).parent / "policy" / "instructions.md"
TOP_K = 5
MAX_HISTORY_MESSAGES = 6
MAX_OUTPUT_TOKENS = 16000


def build_request(conversation: Conversation) -> tuple[list[str], list[dict[str, str]]]:
    _, instructions = corpus.front_matter(INSTRUCTIONS.read_text(encoding="utf-8"))
    hits = corpus.retrieve(conversation.question, TOP_K)
    articles = "\n\n".join(f"[{hit.node.node_id}] {hit.node.get_content()}" for hit in hits)
    system = f"{instructions}\n\nHelp-center articles:\n\n{articles}"
    messages = [{"role": turn.role, "content": turn.text} for turn in conversation.turns[-MAX_HISTORY_MESSAGES:]]
    messages.append({"role": "user", "content": conversation.question})
    return [system], messages


def answer(conversation: Conversation, provider: str, model: str | None, *, out: TextIO = sys.stdout) -> str | None:
    system, messages = build_request(conversation)
    if provider == "none":
        cli.show_request(system, messages, out)
        return None
    return providers.ask(provider, model, system, messages, MAX_OUTPUT_TOKENS)


if __name__ == "__main__":
    sys.exit(cli.run(cli.parser(__doc__).parse_args(), answer))

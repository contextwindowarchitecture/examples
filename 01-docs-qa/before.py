"""The help-center bot as it is usually written: retrieve, paste the chunks into the system prompt, keep the last few
messages, send. It works. What it cannot tell you is what it sent, what it left out, and why.
Compare build_request() with the one in after.py.

    uv run before.py "How do I export all my projects?"                          # prints the request it would send
    uv run before.py --conversation scenarios/02-long-conversation/conversation.json
    uv run --env-file .env before.py --provider anthropic "How do I export all my projects?"
    uv run --env-file .env before.py --provider anthropic --record runs/export-before "How do I export all my projects?"

--record DIR writes the conversation (conversation.json), the request as built (request.json) and the reply (run.json).
"""
from __future__ import annotations

import json
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


def answer(conversation: Conversation, provider: str, model: str | None, *, out: TextIO = sys.stdout,
           record: str | Path | None = None) -> str | None:
    system, messages = build_request(conversation)
    if record:
        # --record: the request as built. Nothing recorded what was left out, so there is no trace to keep beside it.
        Path(record).mkdir(parents=True, exist_ok=True)
        request = {"system": system, "messages": messages}
        (Path(record) / "request.json").write_text(json.dumps(request, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if provider == "none":
        cli.show_request(system, messages, out)
        return None
    return providers.ask(provider, model, system, messages, MAX_OUTPUT_TOKENS)


def main(argv: list[str]) -> int:
    args = cli.parser(__doc__).parse_args(argv)
    return cli.run(args, lambda conversation, provider, model: answer(conversation, provider, model, record=args.record))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""The command line both apps share: ask one question, replay a scenario's conversation, or chat."""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from typing import TextIO

from conversation import Conversation
from providers import ProviderError

# answer(conversation, provider, model) -> the model's reply, or None when nothing was sent
Answer = Callable[[Conversation, str, str | None], str | None]


def parser(doc: str | None) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=doc, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("question", nargs="?", help="one question to ask; omit it to chat")
    p.add_argument("--conversation", metavar="FILE",
                   help="a conversation file, such as scenarios/02-long-conversation/conversation.json")
    p.add_argument("--provider", choices=["none", "anthropic", "openai"], default=os.environ.get("DOCS_QA_PROVIDER", "none"),
                   help="where to send the request; none, the default, prints it instead")
    p.add_argument("--model", default=os.environ.get("DOCS_QA_MODEL"), help="the model to ask (default: the provider's)")
    return p


def show_request(system: list[str], messages: list[dict[str, str]], out: TextIO = sys.stdout) -> None:
    """The request exactly as it would be sent, for a dry run."""
    for text in system:
        print("\n── system ──\n" + text, file=out)
    for message in messages:
        print(f"\n── {message['role']} ──\n" + message["content"], file=out)


def run(args: argparse.Namespace, answer: Answer) -> int:
    if args.conversation or args.question:
        if args.conversation:
            conversation = Conversation.load(args.conversation)
        else:
            conversation = Conversation.new()
            conversation.ask(args.question)
        try:
            reply = answer(conversation, args.provider, args.model)
        except ProviderError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        if reply is not None:
            print("\n" + reply)
        return 0
    if args.provider == "none":
        print("chatting needs a model: pass --provider anthropic or --provider openai (see README.md)", file=sys.stderr)
        return 2
    return _chat(args, answer)


def _chat(args: argparse.Namespace, answer: Answer) -> int:
    conversation = Conversation.new()
    print(f"Ask about Fernway (session {conversation.session}). Ctrl-D to quit.")
    while True:
        try:
            question = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not question:
            continue
        conversation.ask(question)
        try:
            reply = answer(conversation, args.provider, args.model)
        except ProviderError as error:
            print(f"error: {error}", file=sys.stderr)
            conversation.unanswered()
            continue
        if reply is None:
            # Nothing was sent (after.py refused). The application recovers, here by asking for more context.
            print("\nfernway> I couldn't find that in the Fernway help center. Could you rephrase or add detail? "
                  "You can also reach support@fernway.example.")
            conversation.unanswered()
            continue
        print(f"\nfernway> {reply}")
        conversation.answered(reply)

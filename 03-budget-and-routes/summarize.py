"""Summaries computed ahead of time, the variants assembly may choose instead of a long body (R-18).

Assembly never calls a model, so a summary has to exist before the snapshot is frozen. This script writes them:

    uv run summarize.py --provider openai --help-center          # summarize every paragraph whose text changed
    uv run summarize.py --provider openai --conversation FILE    # summarize the long turns of a conversation file

Help-center summaries are cached in help-center/summaries.json by the SHA-256 of the paragraph they summarize, so an
edited paragraph loses its summary until this runs again, and a stale one is never offered as a variant. In chat,
app.py summarizes each long turn the same way when it is saved. The model defaults to the small route's for the
provider. Read what it writes before committing it: a summary must not add an instruction or a fact (R-18).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import corpus
import providers
import routes

METHOD = "summarize/v1"
SUMMARIES = corpus.HELP_CENTER / "summaries.json"
LONG_TURN_BYTES = 160  # turns shorter than about 40 tokens are not worth a summary

PROMPT = (
    "You shorten text for a support assistant whose context window is small. Rewrite the text you are given as one "
    "sentence of at most 25 words. Keep every number, limit, plan name, role, menu path and article id it states. "
    "Add nothing it does not state, and do not address the reader. Reply with the sentence only."
)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def summarize(text: str, provider: str, options: dict, attempts: int = 3) -> str:
    """One sentence for the text. A reasoning model can spend its output on thinking and return nothing; an empty
    variant is invalid, so try again, and fail rather than save one."""
    for _ in range(attempts):
        summary = providers.ask(provider, options, [PROMPT], [{"role": "user", "content": text}], max_tokens=2000)
        if summary.strip():
            return " ".join(summary.split())
    raise providers.ProviderError(f"no summary after {attempts} attempts for: {text[:60]}...")


def method(options: dict) -> str:
    """How a summary was made, recorded with it and in every trace that uses it."""
    return f"{METHOD} {options['model']}"


def needs_summary(text: str) -> bool:
    return len(text.encode("utf-8")) > LONG_TURN_BYTES


def load_summaries() -> dict:
    return json.loads(SUMMARIES.read_text(encoding="utf-8")) if SUMMARIES.exists() else {}


def save_summaries(summaries: dict) -> None:
    SUMMARIES.write_text(json.dumps(dict(sorted(summaries.items())), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def help_center(provider: str, options: dict) -> int:
    summaries = load_summaries()
    current = {node.node_id: node.get_content() for node in corpus.nodes()}
    stale = sorted(chunk_id for chunk_id in summaries if chunk_id not in current or not summaries[chunk_id]["text"].strip())
    for chunk_id in stale:  # a paragraph that was removed, or a summary that came back empty
        del summaries[chunk_id]
    written = 0
    for chunk_id, text in current.items():
        if summaries.get(chunk_id, {}).get("sha256") == sha256(text):
            continue
        summaries[chunk_id] = {"sha256": sha256(text), "method": method(options), "text": summarize(text, provider, options)}
        save_summaries(summaries)  # after each one, so an interrupted run keeps what it paid for
        written += 1
        print(f"{chunk_id}: {summaries[chunk_id]['text']}", flush=True)
    save_summaries(summaries)
    print(f"{written} summarized, {len(stale)} removed, {len(summaries)} in {SUMMARIES.name}")
    return 0


def conversation(path: str, provider: str, options: dict) -> int:
    file = Path(path)
    data = json.loads(file.read_text(encoding="utf-8"))
    for turn in data["turns"]:
        if needs_summary(turn["text"]) and "summary" not in turn:
            turn["summary"] = {"method": method(options), "text": summarize(turn["text"], provider, options)}
            print(f"{turn['role']}: {turn['summary']['text']}", flush=True)
    file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--help-center", action="store_true")
    target.add_argument("--conversation", metavar="FILE")
    parser.add_argument("--provider", choices=["anthropic", "openai"], default=os.environ.get("DOCS_QA_PROVIDER", "anthropic"))
    parser.add_argument("--model", help="default: the small route's model for the provider")
    args = parser.parse_args(argv)
    options = {"model": args.model} if args.model else dict(routes.load(routes.default()).models[args.provider])
    try:
        return help_center(args.provider, options) if args.help_center else conversation(args.conversation, args.provider, options)
    except providers.ProviderError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

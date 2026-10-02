"""The Fernway help center as retrievable chunks.

Each article in help-center/ starts with a front matter block (id, title, version, updated), and every paragraph after
it is one chunk. Retrieval is LlamaIndex's BM25Retriever: no API key, no model download, and the same scores on every
machine, which keeps the committed scenarios byte-stable. help-center/summaries.json holds a summary of each chunk,
written ahead of time by summarize.py.
"""
from __future__ import annotations

import hashlib
import json
from functools import cache
from pathlib import Path
from typing import Any

from llama_index.core.schema import NodeWithScore, TextNode
from llama_index.retrievers.bm25 import BM25Retriever

HELP_CENTER = Path(__file__).parent / "help-center"
SUMMARIES = HELP_CENTER / "summaries.json"


@cache
def _summaries() -> dict[str, Any]:
    return json.loads(SUMMARIES.read_text(encoding="utf-8")) if SUMMARIES.exists() else {}


def summary(node: TextNode) -> dict[str, str] | None:
    """The chunk's summary, {"method", "text"}, only if it was made from the chunk's current text. An edited paragraph
    has none until summarize.py runs again, so a stale summary is never offered in its place."""
    entry = _summaries().get(node.node_id)
    if entry and entry["text"].strip() and entry["sha256"] == hashlib.sha256(node.get_content().encode("utf-8")).hexdigest():
        return {"method": entry["method"], "text": entry["text"]}
    return None


def front_matter(text: str) -> tuple[dict[str, str], str]:
    """Split a leading `---` block of `key: value` lines from the body that follows it."""
    head, sep, body = text.partition("\n---\n")
    if not text.startswith("---\n") or not sep:
        raise ValueError("expected a --- front matter block")
    fields = {}
    for line in head.splitlines()[1:]:
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, body.strip()


@cache
def nodes() -> tuple[TextNode, ...]:
    """Every paragraph of every article, in file order. A chunk id names the article, its version and the paragraph,
    so an edited article gets new ids and a cited id always means the text it was cited for."""
    found = []
    for path in sorted(HELP_CENTER.glob("*.md")):
        meta, body = front_matter(path.read_text(encoding="utf-8"))
        paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
        for index, paragraph in enumerate(paragraphs):
            found.append(TextNode(
                id_=f"help:{meta['id']}@{meta['version']}#{index}",
                text=paragraph,
                metadata={"article": meta["id"], "title": meta["title"], "version": meta["version"], "updated": meta["updated"]},
                # The title is indexed with the paragraph; the rest is bookkeeping, not text to match.
                excluded_embed_metadata_keys=["article", "version", "updated"],
                excluded_llm_metadata_keys=["article", "title", "version", "updated"],
            ))
    return tuple(found)


@cache
def _retriever(top_k: int) -> BM25Retriever:
    return BM25Retriever.from_defaults(nodes=list(nodes()), similarity_top_k=top_k)


def retrieve(question: str, top_k: int) -> list[NodeWithScore]:
    """The top_k chunks for a question, best first. Equal scores are ordered by chunk id, so the order never depends
    on how the index was built."""
    hits = _retriever(top_k).retrieve(question)
    return sorted(hits, key=lambda hit: (-(hit.score or 0.0), hit.node.node_id))

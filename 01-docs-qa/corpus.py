"""The Fernway help center as retrievable chunks, shared by before.py and after.py.

Each article in help-center/ starts with a front matter block (id, title, version, updated), and every paragraph after
it is one chunk. Retrieval is LlamaIndex's BM25Retriever: no API key, no model download, and the same scores on every
machine, which keeps the committed scenarios byte-stable.
"""
from __future__ import annotations

from functools import cache
from pathlib import Path

from llama_index.core.schema import NodeWithScore, TextNode
from llama_index.retrievers.bm25 import BM25Retriever

HELP_CENTER = Path(__file__).parent / "help-center"


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
def _retriever() -> BM25Retriever:
    # Every chunk is scored. BM25's own top-k picks among equal scores in whatever order numpy's argpartition leaves
    # them, which differs between machines (arm64 and x86_64 use different sorting kernels).
    return BM25Retriever.from_defaults(nodes=list(nodes()), similarity_top_k=len(nodes()))


def retrieve(question: str, top_k: int) -> list[NodeWithScore]:
    """The top_k chunks for a question, best first. Every chunk is ranked by score, then by chunk id, before the top
    k are taken, so equal scores resolve the same way on every machine and the committed scenarios hold everywhere."""
    hits = _retriever().retrieve(question)
    return sorted(hits, key=lambda hit: (-(hit.score or 0.0), hit.node.node_id))[:top_k]

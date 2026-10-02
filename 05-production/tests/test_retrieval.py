"""Retrieval returns the same chunks on every machine, ties included, so the committed scenarios hold everywhere."""
from __future__ import annotations

import corpus


def ranked(question: str, top_k: int) -> list[tuple[str, float]]:
    return [(hit.node.node_id, hit.score or 0.0) for hit in corpus.retrieve(question, top_k)]


def test_the_top_k_are_the_first_k_of_the_full_ranking() -> None:
    # Nothing in the help center matches a banana-bread recipe, so most chunks tie at a score of 0. BM25's own top-k
    # selection picks among ties in whatever order numpy's argpartition leaves them, which differs between machines.
    question = "What's a good recipe for banana bread?"
    everything = ranked(question, len(corpus.nodes()))
    assert ranked(question, 5) == everything[:5]
    assert everything == sorted(everything, key=lambda hit: (-hit[1], hit[0]))

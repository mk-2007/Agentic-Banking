"""A small, dependency-free BM25 index.

BM25 ranks by how rare and how frequent the query's words are in each chunk. It needs no model
download, behaves identically on every machine, and is strong for policy text full of exact terms
(limits, fees, section names). Dense embeddings can later sit behind the same interface and be
compared on the same evaluation set.
"""

import math
from collections import Counter

from nexa.domain.knowledge import Chunk

from .text import tokenize

K1 = 1.5
B = 0.75


def index_text(chunk: Chunk) -> str:
    """Return the text a chunk is indexed under: its heading path plus its body."""
    return f"{' '.join(chunk.heading_path)} {chunk.text}"


class Bm25Index:
    """BM25 over a fixed set of chunks. Immutable after construction."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self._chunks = chunks
        self._tf = [Counter(tokenize(index_text(c))) for c in chunks]
        self._len = [sum(tf.values()) for tf in self._tf]
        self._avg_len = (sum(self._len) / len(chunks)) if chunks else 0.0
        document_frequency: Counter[str] = Counter()
        for tf in self._tf:
            document_frequency.update(tf.keys())
        total = len(chunks)
        self._idf = {
            term: math.log(1 + (total - df + 0.5) / (df + 0.5))
            for term, df in document_frequency.items()
        }

    def __len__(self) -> int:
        """Return the number of indexed chunks."""
        return len(self._chunks)

    def search(self, weighted_terms: dict[str, float], top_k: int) -> list[tuple[Chunk, float]]:
        """Return up to ``top_k`` (chunk, score) pairs, best first, ties broken by chunk id."""
        scored: list[tuple[Chunk, float]] = []
        for chunk, tf, length in zip(self._chunks, self._tf, self._len, strict=True):
            score = 0.0
            for term, weight in weighted_terms.items():
                freq = tf.get(term, 0)
                if freq:
                    norm = freq * (K1 + 1) / (freq + K1 * (1 - B + B * length / self._avg_len))
                    score += weight * self._idf[term] * norm
            if score > 0:
                scored.append((chunk, score))
        scored.sort(key=lambda pair: (-pair[1], pair[0].id))
        return scored[:top_k]

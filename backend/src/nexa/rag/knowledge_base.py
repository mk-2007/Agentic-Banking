"""The knowledge base: search over chunks with access control applied *before* ranking.

Security design: there is one index per clearance level, and each index contains only the chunks
that level may see. A customer-channel query is therefore run against an index in which
restricted and internal material does not exist. It cannot be ranked, scored or counted, so there is
no side channel to leak through. Filtering after ranking would be weaker.
"""

import json
from pathlib import Path
from typing import Protocol

from nexa.domain.knowledge import Chunk, DocumentStatus, RetrievalHit, Sensitivity

from .bm25 import Bm25Index
from .ingest import default_data_dir, load_corpus
from .text import tokenize

EXPANSION_WEIGHT = 0.5
MAX_TOP_K = 20


class KnowledgeSearch(Protocol):
    """What the tool layer needs from a knowledge base."""

    def search(
        self,
        query: str,
        *,
        clearance: Sensitivity,
        top_k: int = 4,
        include_historical: bool = False,
        product: str | None = None,
    ) -> list[RetrievalHit]:
        """Return ranked hits visible at ``clearance``."""
        ...


class SynonymExpander:
    """Adds equivalent expressions to a query (KB section 18), at lower weight."""

    def __init__(self, groups: list[list[str]]) -> None:
        self._groups = [[tuple(tokenize(phrase)) for phrase in group] for group in groups]

    @staticmethod
    def _contains(tokens: list[str], phrase: tuple[str, ...]) -> bool:
        n = len(phrase)
        return n > 0 and any(tuple(tokens[i : i + n]) == phrase for i in range(len(tokens) - n + 1))

    def expand(self, tokens: list[str]) -> dict[str, float]:
        """Return query terms: originals at weight 1, synonyms at a lower weight."""
        terms = {token: 1.0 for token in tokens}
        for group in self._groups:
            if any(self._contains(tokens, phrase) for phrase in group):
                for phrase in group:
                    for token in phrase:
                        terms.setdefault(token, EXPANSION_WEIGHT)
        return terms


class KnowledgeBase:
    """Searchable corpus with per-clearance indexes."""

    def __init__(self, chunks: tuple[Chunk, ...], synonym_groups: list[list[str]] | None = None):
        self._chunks = chunks
        self._expander = SynonymExpander(synonym_groups or [])
        self._indexes: dict[tuple[Sensitivity, bool], Bm25Index] = {}
        for level in Sensitivity:
            visible = [c for c in chunks if c.meta.sensitivity <= level]
            current = [c for c in visible if c.meta.status is DocumentStatus.ACTIVE]
            self._indexes[(level, False)] = Bm25Index(current)
            # history means superseded versions; drafts and retired documents are never served
            kept = (DocumentStatus.ACTIVE, DocumentStatus.SUPERSEDED)
            self._indexes[(level, True)] = Bm25Index([c for c in visible if c.meta.status in kept])

    @property
    def chunks(self) -> tuple[Chunk, ...]:
        """Every chunk, regardless of access. For ingestion tests, never for retrieval."""
        return self._chunks

    def access_review(self) -> dict[Sensitivity, dict[str, tuple[str, str]]]:
        """For each clearance, the servable documents it may see: id -> (version, status).

        An access-review report: who can read what, from the same filter that serves searches.
        """
        review: dict[Sensitivity, dict[str, tuple[str, str]]] = {}
        for level in Sensitivity:
            docs = review.setdefault(level, {})
            for chunk in self._chunks:
                m = chunk.meta
                if m.sensitivity <= level and m.status is DocumentStatus.ACTIVE:
                    docs[m.document_id] = (m.version, m.status.value)
        return review

    def search(
        self,
        query: str,
        *,
        clearance: Sensitivity,
        top_k: int = 4,
        include_historical: bool = False,
        product: str | None = None,
    ) -> list[RetrievalHit]:
        """Return up to ``top_k`` hits that ``clearance`` may see, best first."""
        if not 1 <= top_k <= MAX_TOP_K:
            raise ValueError(f"top_k must be between 1 and {MAX_TOP_K}")
        terms = self._expander.expand(tokenize(query))
        if not terms:
            return []
        index = self._indexes[(clearance, include_historical)]
        pool = index.search(terms, top_k=len(index) or 1)
        if product is not None:
            pool = [(c, s) for c, s in pool if c.meta.product.lower() == product.lower()]
        return [
            RetrievalHit(chunk=chunk, score=score, rank=rank)
            for rank, (chunk, score) in enumerate(pool[:top_k], start=1)
        ]


def load_knowledge_base(data_dir: Path | None = None) -> KnowledgeBase:
    """Build the knowledge base from the repository's documents and synonym list."""
    root = data_dir or default_data_dir()
    synonyms = json.loads((root / "knowledge_base" / "synonyms.json").read_text(encoding="utf-8"))
    groups = [*synonyms["groups"], *synonyms.get("additional_groups", [])]
    return KnowledgeBase(load_corpus(root), groups)

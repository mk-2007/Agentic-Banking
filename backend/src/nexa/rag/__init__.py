"""Document ingestion, chunking and metadata-filtered retrieval.

Why: Grounds agents in versioned bank policy instead of model memory (PRD section 18, KB
section 19).

Where it sits: Layer 2. Reached only through the tool layer.

Modules:
    parsing         Markdown + front matter -> numbered sections
    chunking        sections -> chunks (FAQ pairs, split tables, packed paragraphs)
    ingest          load documents, attach metadata, resolve versions
    text, bm25      tokenizer and a dependency-free BM25 index
    knowledge_base  per-clearance indexes; access control applied before ranking
"""

from .ingest import chunks_from_texts, load_corpus
from .knowledge_base import KnowledgeBase, KnowledgeSearch, load_knowledge_base

__all__ = [
    "KnowledgeBase",
    "KnowledgeSearch",
    "chunks_from_texts",
    "load_corpus",
    "load_knowledge_base",
]

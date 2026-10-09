"""Document ingestion, chunking, embedding and metadata-filtered retrieval.

Why: Grounds agents in versioned bank policy instead of model memory (PRD section 18, KB
    section 19).

Where it sits: Layer 2. Depends on llm for embeddings.
"""

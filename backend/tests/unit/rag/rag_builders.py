"""Tiny document factory for RAG tests."""


def doc(
    document_id: str = "NB-T-001",
    *,
    version: str = "1.0",
    effective_date: str = "2026-01-01",
    status: str = "Active",
    sensitivity: str = "public",
    extra: str = "",
    body: str = "# 1. Intro\n\nHello world.\n",
) -> str:
    """Return a complete Markdown document with valid front matter."""
    return (
        "---\n"
        f"document_id: {document_id}\n"
        "title: Test Document\n"
        "department: Testing\n"
        "document_type: Policy\n"
        f"version: {version}\n"
        f"effective_date: {effective_date}\n"
        f"status: {status}\n"
        "access_level: Internal Prototype\n"
        "product: General Banking\n"
        "jurisdiction: Pakistan Prototype\n"
        f"sensitivity: {sensitivity}\n"
        f"{extra}"
        "---\n\n"
        f"{body}"
    )

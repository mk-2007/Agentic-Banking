"""Load documents from disk into chunks with metadata and resolve document versions.

Every document is Markdown with front matter holding the metadata fields from KB section 19.2
plus `sensitivity`. A document may also declare `section_sensitivity` (for example
``13=internal, 17=internal``) to make parts of it more restricted than the rest.
"""

from datetime import date
from pathlib import Path

from nexa.domain.knowledge import Chunk, DocumentMeta, DocumentStatus, Sensitivity

from .chunking import DEFAULT_MAX_WORDS, chunk_section
from .parsing import ParsedDocument, parse_document

REQUIRED_FIELDS = (
    "document_id", "title", "department", "document_type", "version",
    "effective_date", "status", "access_level", "product", "jurisdiction", "sensitivity",
)  # fmt: skip


def default_data_dir() -> Path:
    """Return the repository's ``data`` directory for a normal checkout."""
    return Path(__file__).resolve().parents[4] / "data"


def meta_from_front_matter(fields: dict[str, str]) -> DocumentMeta:
    """Build validated `DocumentMeta`, failing loudly if any field is missing."""
    missing = [name for name in REQUIRED_FIELDS if name not in fields]
    if missing:
        raise ValueError(f"front matter is missing: {missing}")
    return DocumentMeta(
        document_id=fields["document_id"],
        title=fields["title"],
        department=fields["department"],
        document_type=fields["document_type"],
        version=fields["version"],
        effective_date=date.fromisoformat(fields["effective_date"]),
        status=DocumentStatus(fields["status"].lower()),
        access_level=fields["access_level"],
        product=fields["product"],
        jurisdiction=fields["jurisdiction"],
        sensitivity=Sensitivity[fields["sensitivity"].upper()],
    )


def parse_section_overrides(raw: str | None) -> dict[str, Sensitivity]:
    """Parse ``'13=internal, 17.6=restricted'`` into a mapping."""
    overrides: dict[str, Sensitivity] = {}
    for item in (raw or "").split(","):
        if item.strip():
            number, _, level = item.partition("=")
            overrides[number.strip()] = Sensitivity[level.strip().upper()]
    return overrides


def resolve_versions(
    documents: list[tuple[DocumentMeta, ParsedDocument]],
) -> list[tuple[DocumentMeta, ParsedDocument]]:
    """Keep only the newest active version of each document; mark older ones superseded.

    A superseded version stays in the corpus (so history can be searched deliberately) but
    can never be mistaken for current policy (KB section 19.1).
    """
    newest: dict[str, tuple[date, str]] = {}
    for meta, _ in documents:
        if meta.status is DocumentStatus.ACTIVE:
            key = (meta.effective_date, meta.version)
            if meta.document_id not in newest or key > newest[meta.document_id]:
                newest[meta.document_id] = key
    resolved: list[tuple[DocumentMeta, ParsedDocument]] = []
    for meta, parsed in documents:
        is_old = (
            meta.status is DocumentStatus.ACTIVE
            and (meta.effective_date, meta.version) != newest[meta.document_id]
        )
        resolved.append(
            (
                meta.model_copy(update={"status": DocumentStatus.SUPERSEDED}) if is_old else meta,
                parsed,
            )
        )
    return resolved


def chunks_from_texts(texts: list[str], max_words: int = DEFAULT_MAX_WORDS) -> tuple[Chunk, ...]:
    """Parse, version-resolve and chunk a list of document texts."""
    documents: list[tuple[DocumentMeta, ParsedDocument]] = []
    overrides_by_doc: dict[tuple[str, str], dict[str, Sensitivity]] = {}
    for text in texts:
        parsed = parse_document(text)
        meta = meta_from_front_matter(parsed.front_matter)
        overrides_by_doc[(meta.document_id, meta.version)] = parse_section_overrides(
            parsed.front_matter.get("section_sensitivity")
        )
        documents.append((meta, parsed))
    chunks: list[Chunk] = []
    for meta, parsed in resolve_versions(documents):
        overrides = overrides_by_doc[(meta.document_id, meta.version)]
        for ordinal, section in enumerate(parsed.sections):
            chunks.extend(chunk_section(meta, section, overrides, max_words, ordinal))
    ids = [c.id for c in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("chunk ids are not unique (is the same document version loaded twice?)")
    return tuple(chunks)


def load_corpus(
    data_dir: Path | None = None, max_words: int = DEFAULT_MAX_WORDS
) -> tuple[Chunk, ...]:
    """Load the knowledge base and policy documents under ``data_dir``."""
    root = data_dir or default_data_dir()
    paths = sorted((root / "knowledge_base").glob("*.md")) + sorted(
        (root / "policies").glob("*.md")
    )
    return chunks_from_texts([p.read_text(encoding="utf-8") for p in paths], max_words)

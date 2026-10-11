"""Split sections into retrievable chunks.

Rules, chosen so each chunk answers one kind of question and stays self-contained:

- a FAQ question and its answer stay together;
- a table stays whole unless it is long, and long tables are split by rows with the header
  repeated in every piece;
- short list lines and paragraphs are packed together up to ``max_words``;
- every chunk remembers its heading path, which is also indexed, so "10.3 Fraud Handling" is
  findable even when the body text never repeats those words.
"""

from nexa.domain.knowledge import Chunk, DocumentMeta, Sensitivity

from .parsing import Section

DEFAULT_MAX_WORDS = 160
_TABLE_HEADER_LINES = 2


def _words(text: str) -> int:
    return len(text.split())


def _is_table(block: str) -> bool:
    return block.lstrip().startswith("|")


def _split_table(block: str, max_words: int) -> list[str]:
    lines = block.splitlines()
    if _words(block) <= max_words or len(lines) <= _TABLE_HEADER_LINES + 1:
        return [block]
    header, rows = lines[:_TABLE_HEADER_LINES], lines[_TABLE_HEADER_LINES:]
    pieces: list[str] = []
    group: list[str] = []
    for row in rows:
        if group and _words("\n".join([*header, *group, row])) > max_words:
            pieces.append("\n".join([*header, *group]))
            group = []
        group.append(row)
    if group:
        pieces.append("\n".join([*header, *group]))
    return pieces


def _units(blocks: list[str], max_words: int) -> list[tuple[str, bool]]:
    """Turn blocks into (text, atomic) units; atomic units always become their own chunk.

    A FAQ question joins its answer and is atomic. Long tables are split into row groups.
    """
    units: list[tuple[str, bool]] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        if (
            block.startswith("**Q:")
            and index + 1 < len(blocks)
            and blocks[index + 1].startswith("A:")
        ):
            units.append((f"{block}\n{blocks[index + 1]}", True))
            index += 2
            continue
        pieces = _split_table(block, max_words) if _is_table(block) else [block]
        units.extend((piece, False) for piece in pieces)
        index += 1
    return units


def _sensitivity_for(
    meta: DocumentMeta, number: str, overrides: dict[str, Sensitivity]
) -> Sensitivity:
    """Use the most specific override whose section number is a prefix of ``number``."""
    best: tuple[int, Sensitivity] | None = None
    for key, level in overrides.items():
        applies = number == key or number.startswith(f"{key}.")
        if applies and (best is None or len(key) > best[0]):
            best = (len(key), level)
    return best[1] if best else meta.sensitivity


def chunk_section(
    meta: DocumentMeta,
    section: Section,
    overrides: dict[str, Sensitivity],
    max_words: int = DEFAULT_MAX_WORDS,
    ordinal: int = 0,
) -> list[Chunk]:
    """Chunk one section, applying any section-level sensitivity override.

    ``ordinal`` is the section's position in its document. It keeps ids unique for sections
    that have no number (titles and the preamble).
    """
    sensitivity = _sensitivity_for(meta, section.number, overrides)
    chunk_meta = meta.model_copy(update={"sensitivity": sensitivity})
    groups: list[list[str]] = []
    current: list[str] = []
    for unit, atomic in _units(section.blocks, max_words):
        too_big = current and _words("\n\n".join([*current, unit])) > max_words
        if current and (atomic or too_big):
            groups.append(current)
            current = []
        current.append(unit)
        if atomic:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    label = section.number or f"pre{ordinal}"
    return [
        Chunk(
            id=f"{meta.document_id}@{meta.version}:{label}:{n}",
            meta=chunk_meta,
            section=section.number,
            heading_path=section.path,
            text="\n\n".join(group),
        )
        for n, group in enumerate(groups, start=1)
    ]

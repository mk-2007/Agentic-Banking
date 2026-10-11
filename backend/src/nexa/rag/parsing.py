"""Parse a Markdown document with front matter into metadata and numbered sections.

Section numbers come from headings such as ``# 10. Fraud...`` or ``## 10.2 Common Risk...``.
Headings without a number (a document title) get the number ``""``.
"""

import re
from dataclasses import dataclass, field

_HEADING = re.compile(r"^(#{1,3})\s+(.*\S)\s*$")
_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.*)$")


@dataclass
class Section:
    """A heading and the blocks of text under it (until the next heading)."""

    number: str
    title: str
    path: tuple[str, ...]
    blocks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedDocument:
    """Front-matter fields plus the document's sections in order."""

    front_matter: dict[str, str]
    sections: list[Section]


def split_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Split ``---``-delimited ``key: value`` front matter from the body."""
    if not text.startswith("---\n"):
        raise ValueError("document must start with front matter")
    _, header, body = text.split("---\n", 2)
    fields: dict[str, str] = {}
    for line in header.strip().splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, body


def _blocks(lines: list[str]) -> list[str]:
    """Group consecutive non-blank lines into blocks (tables stay in one block)."""
    blocks: list[str] = []
    current: list[str] = []
    for line in lines:
        if line.strip():
            current.append(line.rstrip())
        elif current:
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    return blocks


def parse_document(text: str) -> ParsedDocument:
    """Parse ``text`` (front matter plus Markdown body) into sections."""
    front_matter, body = split_front_matter(text)
    sections: list[Section] = [Section("", "Preamble", ("Preamble",))]
    buffers: list[list[str]] = [[]]
    h1_title = ""
    for line in body.splitlines():
        heading = _HEADING.match(line)
        if not heading:
            buffers[-1].append(line)
            continue
        level, raw_title = len(heading.group(1)), heading.group(2)
        numbered = _NUMBERED.match(raw_title)
        number, title = (numbered.group(1), numbered.group(2)) if numbered else ("", raw_title)
        label = f"{number} {title}".strip()
        if level == 1:
            h1_title = label
            path: tuple[str, ...] = (label,)
        else:
            path = (h1_title, label) if h1_title else (label,)
        sections.append(Section(number, title, path))
        buffers.append([])
    for section, lines in zip(sections, buffers, strict=True):
        section.blocks = _blocks(lines)
    return ParsedDocument(front_matter, [s for s in sections if s.blocks])

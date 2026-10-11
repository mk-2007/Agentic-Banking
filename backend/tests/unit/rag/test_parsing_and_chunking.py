import pytest
from rag_builders import doc

from nexa.domain.knowledge import Sensitivity
from nexa.rag import chunks_from_texts, load_corpus
from nexa.rag.parsing import parse_document, split_front_matter


def test_front_matter_is_split_from_the_body() -> None:
    fields, body = split_front_matter(doc())
    assert fields["document_id"] == "NB-T-001" and fields["sensitivity"] == "public"
    assert body.lstrip().startswith("# 1. Intro")
    with pytest.raises(ValueError, match="front matter"):
        split_front_matter("# no front matter")


def test_sections_get_numbers_and_heading_paths() -> None:
    body = "# 10. Fraud\n\nintro\n\n## 10.2 Risk Indicators\n\nsudden spike\n"
    sections = parse_document(doc(body=body)).sections
    assert [s.number for s in sections] == ["10", "10.2"]
    assert sections[1].path == ("10 Fraud", "10.2 Risk Indicators")


def test_unnumbered_headings_have_an_empty_number() -> None:
    sections = parse_document(doc(body="# Just A Title\n\ntext\n")).sections
    assert sections[0].number == "" and sections[0].title == "Just A Title"


def test_a_table_stays_in_one_block() -> None:
    body = "# 1. T\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n"
    (section,) = parse_document(doc(body=body)).sections
    assert len(section.blocks) == 1 and section.blocks[0].count("\n") == 3


def test_faq_pairs_become_one_chunk_each() -> None:
    body = "# 16. FAQ\n\n**Q: One?**\n\nA: First.\n\n**Q: Two?**\n\nA: Second.\n"
    chunks = chunks_from_texts([doc(body=body)])
    assert len(chunks) == 2
    assert "Q: One?" in chunks[0].text and "A: First." in chunks[0].text
    assert "Two" not in chunks[0].text


def test_long_tables_split_by_rows_with_the_header_repeated() -> None:
    rows = "\n".join(
        f"| term{i} | a fairly long definition number {i} for padding |" for i in range(40)
    )
    body = f"# 15. Glossary\n\n| Term | Definition |\n| --- | --- |\n{rows}\n"
    chunks = chunks_from_texts([doc(body=body)], max_words=60)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.text.startswith("| Term | Definition |\n| --- | --- |")
    kept = "\n".join(c.text for c in chunks)
    assert all(f"term{i} " in kept for i in range(40))  # nothing lost


def test_short_lines_are_packed_but_respect_the_word_budget() -> None:
    lines = "\n\n".join(f"item number {i} has five words" for i in range(30))
    chunks = chunks_from_texts([doc(body=f"# 2. List\n\n{lines}\n")], max_words=40)
    assert 1 < len(chunks) < 30
    assert all(len(c.text.split()) <= 40 for c in chunks)


def test_chunk_ids_are_unique_even_for_unnumbered_sections() -> None:
    body = "# Title One\n\ntext\n\n# Title Two\n\nmore text\n"
    ids = [c.id for c in chunks_from_texts([doc(body=body)])]
    assert len(ids) == len(set(ids))


def test_section_sensitivity_overrides_apply_most_specific_first() -> None:
    body = (
        "# 12. Public\n\na\n\n# 13. Governance\n\nb\n\n## 13.1 Role\n\nc\n\n"
        "# 17. Edge\n\nd\n\n## 17.6 Flagged\n\ne\n"
    )
    extra = "section_sensitivity: 13=internal, 17=internal, 17.6=restricted\n"
    by_section = {
        c.section: c.meta.sensitivity for c in chunks_from_texts([doc(body=body, extra=extra)])
    }
    assert by_section["12"] is Sensitivity.PUBLIC
    assert by_section["13"] is by_section["13.1"] is Sensitivity.INTERNAL
    assert by_section["17"] is Sensitivity.INTERNAL
    assert by_section["17.6"] is Sensitivity.RESTRICTED


# --- the real corpus -----------------------------------------------------
def test_real_corpus_covers_every_knowledge_base_section() -> None:
    chunks = [c for c in load_corpus() if c.meta.document_id == "NB-KB-001"]
    top_level = {c.section.split(".")[0] for c in chunks if c.section}
    assert top_level >= {str(n) for n in range(1, 20)}


def test_real_corpus_sensitivity_labels() -> None:
    by_doc_section = {(c.meta.document_id, c.section): c.meta.sensitivity for c in load_corpus()}
    # Sections 13 and 17 have no text of their own; their subsections carry the label.
    for section in ("13.1", "13.4", "13.5", "17.1", "17.6", "17.8", "18", "19.1", "19.2"):
        assert by_doc_section[("NB-KB-001", section)] is Sensitivity.INTERNAL, section
    for section in ("3.1", "4.2", "7.3", "9", "10.2", "16"):
        assert by_doc_section[("NB-KB-001", section)] is Sensitivity.PUBLIC, section
    for doc_id in ("NB-POL-FRAUD-001", "NB-POL-AML-001"):
        levels = {s for (d, _), s in by_doc_section.items() if d == doc_id}
        assert levels == {Sensitivity.RESTRICTED}
    levels = {s for (d, _), s in by_doc_section.items() if d == "NB-POL-AUTH-001"}
    assert levels == {Sensitivity.INTERNAL}


def test_real_corpus_chunks_all_carry_complete_metadata() -> None:
    chunks = load_corpus()
    assert len(chunks) > 50
    for chunk in chunks:
        meta = chunk.meta
        assert meta.version and meta.jurisdiction and meta.access_level and chunk.text.strip()
        assert chunk.policy_ref().doc_id == meta.document_id

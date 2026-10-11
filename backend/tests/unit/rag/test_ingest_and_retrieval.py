import pytest
from rag_builders import doc

from nexa.domain.knowledge import DocumentStatus, Sensitivity
from nexa.rag import KnowledgeBase, chunks_from_texts, load_knowledge_base
from nexa.rag.evaluation import evaluate, load_eval_items

BODY_V1 = "# 1. Limits\n\nThe daily transfer limit is PKR 100,000.\n"
BODY_V2 = "# 1. Limits\n\nThe daily transfer limit is PKR 500,000.\n"


def kb_from(*texts: str) -> KnowledgeBase:
    return KnowledgeBase(chunks_from_texts(list(texts)))


# --- metadata and versions ----------------------------------------------
def test_missing_metadata_is_rejected() -> None:
    broken = doc().replace("jurisdiction: Pakistan Prototype\n", "")
    with pytest.raises(ValueError, match="jurisdiction"):
        chunks_from_texts([broken])


def test_loading_the_same_version_twice_is_rejected() -> None:
    with pytest.raises(ValueError, match="not unique"):
        chunks_from_texts([doc(), doc()])


def test_older_active_versions_are_marked_superseded() -> None:
    chunks = chunks_from_texts(
        [
            doc("NB-T-001", version="1.0", effective_date="2025-01-01", body=BODY_V1),
            doc("NB-T-001", version="2.0", effective_date="2026-01-01", body=BODY_V2),
        ]
    )
    status = {c.meta.version: c.meta.status for c in chunks}
    assert status == {"1.0": DocumentStatus.SUPERSEDED, "2.0": DocumentStatus.ACTIVE}


def test_default_search_returns_only_current_policy() -> None:
    kb = kb_from(
        doc("NB-T-001", version="1.0", effective_date="2025-01-01", body=BODY_V1),
        doc("NB-T-001", version="2.0", effective_date="2026-01-01", body=BODY_V2),
    )
    hits = kb.search("daily transfer limit", clearance=Sensitivity.PUBLIC)
    assert [h.chunk.meta.version for h in hits] == ["2.0"]
    assert "500,000" in hits[0].chunk.text


def test_history_is_searchable_only_when_asked_for() -> None:
    kb = kb_from(
        doc("NB-T-001", version="1.0", effective_date="2025-01-01", body=BODY_V1),
        doc("NB-T-001", version="2.0", effective_date="2026-01-01", body=BODY_V2),
    )
    hits = kb.search("daily transfer limit", clearance=Sensitivity.PUBLIC, include_historical=True)
    assert {h.chunk.meta.version for h in hits} == {"1.0", "2.0"}


def test_draft_documents_are_not_retrieved_by_default() -> None:
    kb = kb_from(doc(status="Draft", body=BODY_V1))
    assert kb.search("daily transfer limit", clearance=Sensitivity.RESTRICTED) == []


# --- search mechanics ------------------------------------------------------
def test_synonyms_bridge_wording() -> None:
    body = "# 1. Ratios\n\nDebt-to-income ratio above fifty percent needs review.\n"
    groups = [["debt-to-income ratio", "DTI", "debt burden"]]
    kb = KnowledgeBase(chunks_from_texts([doc(body=body)]), groups)
    assert kb.search("my DTI is high", clearance=Sensitivity.PUBLIC)
    assert (
        KnowledgeBase(chunks_from_texts([doc(body=body)])).search(
            "my DTI is high", clearance=Sensitivity.PUBLIC
        )
        == []
    )


def test_headings_are_searchable() -> None:
    body = "# 10. Fraud\n\n## 10.3 Fraud Handling\n\nIdentify the activity.\n"
    kb = kb_from(doc(body=body))
    (hit,) = kb.search("fraud handling", clearance=Sensitivity.PUBLIC, top_k=1)
    assert hit.chunk.section == "10.3"


def test_results_are_ranked_and_deterministic() -> None:
    kb = load_knowledge_base()
    first = kb.search("daily ATM withdrawal limit", clearance=Sensitivity.PUBLIC, top_k=5)
    again = kb.search("daily ATM withdrawal limit", clearance=Sensitivity.PUBLIC, top_k=5)
    assert [h.chunk.id for h in first] == [h.chunk.id for h in again]
    assert [h.rank for h in first] == [1, 2, 3, 4, 5]
    assert [h.score for h in first] == sorted((h.score for h in first), reverse=True)


def test_empty_and_stopword_only_queries_return_nothing() -> None:
    kb = load_knowledge_base()
    assert kb.search("   ", clearance=Sensitivity.PUBLIC) == []
    assert kb.search("the of and", clearance=Sensitivity.PUBLIC) == []


def test_top_k_is_bounded() -> None:
    kb = load_knowledge_base()
    for bad in (0, 21):
        with pytest.raises(ValueError, match="top_k"):
            kb.search("fees", clearance=Sensitivity.PUBLIC, top_k=bad)


def test_product_filter() -> None:
    kb = load_knowledge_base()
    assert kb.search("fees", clearance=Sensitivity.PUBLIC, product="General Banking")
    assert kb.search("fees", clearance=Sensitivity.PUBLIC, product="Mortgages") == []


# --- retrieval quality ----------------------------------------------------------
def test_retrieval_quality_on_the_labelled_questions() -> None:
    kb = load_knowledge_base()
    result = evaluate(kb, load_eval_items())
    assert result.items >= 40
    assert result.misses == (), f"questions with no correct section in the top 5: {result.misses}"
    assert result.recall_at_3 >= 0.85
    assert result.mean_reciprocal_rank >= 0.8


def test_evaluation_labels_point_at_real_sections() -> None:
    kb = load_knowledge_base()
    existing = {f"{c.meta.document_id}:{c.section}" for c in kb.chunks}
    for item in load_eval_items():
        for expected in item["expected"]:  # type: ignore[attr-defined]
            assert expected in existing, f"{item['id']}: no such section {expected}"

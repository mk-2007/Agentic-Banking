"""Measure retrieval quality on a labelled question set.

Each item names the sections a good answer must come from. We report recall@k (is a correct section
in the top k?) and mean reciprocal rank (how high is the first correct one?). The same function
scores any future retriever (dense, hybrid), so changes are compared on identical questions.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from nexa.config import effective_clearance
from nexa.domain.actors import Role, SessionChannel

from .ingest import default_data_dir
from .knowledge_base import KnowledgeSearch


@dataclass(frozen=True)
class EvalResult:
    """Scores over an evaluation set, plus the questions that missed."""

    items: int
    recall_at_1: float
    recall_at_3: float
    mean_reciprocal_rank: float
    misses: tuple[str, ...]


def load_eval_items(data_dir: Path | None = None) -> list[dict[str, object]]:
    """Load the labelled retrieval questions."""
    path = (data_dir or default_data_dir()) / "knowledge_base" / "retrieval_eval.json"
    items: list[dict[str, object]] = json.loads(path.read_text(encoding="utf-8"))["items"]
    return items


def evaluate(kb: KnowledgeSearch, items: list[dict[str, object]], top_k: int = 5) -> EvalResult:
    """Score ``kb`` on ``items``, searching with each item's own role and channel."""
    at1 = at3 = 0
    reciprocal = 0.0
    misses: list[str] = []
    for item in items:
        clearance = effective_clearance(
            Role(str(item["role"])), SessionChannel(str(item["channel"]))
        )
        assert clearance is not None, f"role {item['role']} has no clearance"
        expected = {str(e) for e in item["expected"]}  # type: ignore[attr-defined]
        hits = kb.search(str(item["query"]), clearance=clearance, top_k=top_k)
        ranks = [
            h.rank for h in hits if f"{h.chunk.meta.document_id}:{h.chunk.section}" in expected
        ]
        if not ranks:
            misses.append(str(item["id"]))
            continue
        first = min(ranks)
        at1 += first == 1
        at3 += first <= 3
        reciprocal += 1 / first
    n = len(items)
    return EvalResult(n, at1 / n, at3 / n, reciprocal / n, tuple(misses))

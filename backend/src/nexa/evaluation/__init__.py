"""Scoring: compare what the platform recommended with what correct handling looks like.

Why: the admin lab runs many labelled cases and needs one honest answer to "how good is the
system?". Scoring is pure: it reads a finished `CaseRun` and the case's label, and changes nothing.

Where it sits: above orchestration and below the API. It never touches the bank; the label lives
in the lab dataset, never in anything an agent can read.

Modules:
    scoring    per-case checks (safe? useful?) and the scorecard over many cases
"""

from .scoring import ArchetypeTally, CaseScore, Check, Scorecard, score_case, scorecard

__all__ = ["ArchetypeTally", "CaseScore", "Check", "Scorecard", "score_case", "scorecard"]

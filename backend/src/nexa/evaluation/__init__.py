"""Scoring: compare what the platform recommended with what correct handling looks like.

Why: the admin lab runs many labelled cases and needs one honest answer to "how good is the
system?". Scoring is pure: it reads a finished `CaseRun` and the case's label, and changes nothing.

Where it sits: above orchestration and below the API. It never touches the bank's write side; the
label lives in the lab dataset, never in anything an agent can read.

Modules:
    scoring    per-case checks (safe, useful, preferred) and the scorecard over many cases
    baselines  simple rules scored on the same cases, for a fair comparison
    hostile    deliberately misbehaving stand-in models behind the real gates
    live       a real model against the rules, behind the same gates
"""

from .baselines import BASELINES, BaselineResult, run_baselines
from .hostile import HostileResult, run_hostile
from .live import LiveCase, LiveSummary, compare_live
from .scoring import ArchetypeTally, CaseScore, Check, Scorecard, judge, score_case, scorecard

__all__ = [
    "BASELINES",
    "ArchetypeTally",
    "BaselineResult",
    "CaseScore",
    "Check",
    "HostileResult",
    "LiveCase",
    "LiveSummary",
    "Scorecard",
    "compare_live",
    "judge",
    "run_baselines",
    "run_hostile",
    "score_case",
    "scorecard",
]

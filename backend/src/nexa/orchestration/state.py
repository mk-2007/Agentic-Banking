"""The data a case carries through the graph.

Every value is a pydantic `Contract`, an enum, or a *list* of those. That is deliberate: the graph
will be checkpointed (to pause for human approval and resume later), and the checkpoint serializer
turns bare tuples and dataclasses into lists and dicts. Contracts are re-validated on the way
back, so they come back exactly as they went in. Collections at the top level are lists for the
same reason.
"""

import operator
from typing import Annotated, TypedDict

from nexa.agents import Dossier, PolicyResult, VerificationReport
from nexa.domain.approval import ApprovalRequest, ApprovalStatus, ApprovalVote
from nexa.domain.case import Case, CaseStatus
from nexa.domain.decision import Decision
from nexa.domain.evidence import Evidence


class CaseGraphState(TypedDict, total=False):
    """State of one case run. Nodes return only the keys they change."""

    case: Case
    # Every status the case has been in, in order. Lists are appended to, not replaced.
    trail: Annotated[list[CaseStatus], operator.add]
    dossier: Dossier
    findings: list[Evidence]
    policy: PolicyResult
    verification: VerificationReport
    # Set when the run stopped early. A short code such as "get_kyc_status:out_of_scope", never
    # free text from a tool, so it is safe to log and to show.
    failure: str
    # Set once a decision provider has proposed an action (Phase 6b).
    decision: Decision
    # Set when the recommended action needs humans; built by orchestration, never by a model.
    approval_request: ApprovalRequest
    # Every vote received so far across resumes. Lists are appended to, not replaced.
    votes: Annotated[list[ApprovalVote], operator.add]
    approval: ApprovalStatus
    # How many times the run has paused for votes; bounded by `RunLimits.max_vote_rounds`.
    rounds: int

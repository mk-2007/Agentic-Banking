"""The shapes the API accepts and returns.

Responses are deliberately small and safe to show: statuses, codes, ids, our own finding
summaries and cited policy references. They never include the dossier, so merchant names and
memos (third-party text) and customer details stay inside the platform.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nexa.agents.findings import code_of, signal_of
from nexa.domain.approval import Verdict
from nexa.orchestration import CaseRun


class Request(BaseModel):
    """Base for request bodies: unknown fields are rejected, text is trimmed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OpenCaseRequest(Request):
    """The alert a new case starts from. It must match the bank's records."""

    account_id: str = Field(min_length=1, max_length=64)
    customer_id: str = Field(min_length=1, max_length=64)
    transaction_id: str = Field(min_length=1, max_length=64)
    trigger: str = Field(min_length=1, max_length=120)


class VoteRequest(Request):
    """A human's verdict. Who they are and their role come from the token, not from here."""

    verdict: Verdict
    comment: str = Field(default="", max_length=500)


class ChatRequest(Request):
    """A question for the knowledge base."""

    question: str = Field(min_length=2, max_length=500)


PaymentCategory = Literal[
    "grocery",
    "dining",
    "fuel",
    "pharmacy",
    "retail",
    "electronics",
    "telecom",
    "utilities",
    "travel",
    "cash",
    "transfer",
]
PaymentChannel = Literal["pos", "atm", "card_online", "mobile_app", "web", "transfer"]


class PaymentRequest(Request):
    """A payment a customer makes in the app.

    ``device`` and ``failed_logins`` stand in for what a bank's own systems observe; in this
    prototype the page lets you set them to simulate a stolen phone or a password guesser. Whether
    the payee is a new beneficiary is never asked: the bank works that out from the history.
    """

    account_id: str = Field(min_length=1, max_length=64)
    amount: int = Field(gt=0, le=5_000_000, description="Whole PKR.")
    merchant_name: str = Field(min_length=1, max_length=80, pattern=r"^[\w .&'\-]+$")
    merchant_category: PaymentCategory
    country: str = Field(pattern=r"^[A-Za-z]{2}$")
    city: str = Field(min_length=1, max_length=60, pattern=r"^[\w .'\-]+$")
    channel: PaymentChannel
    payee_account: str | None = Field(default=None, max_length=40, pattern=r"^[\w\-]+$")
    device: Literal["registered", "new"] = "registered"
    failed_logins: int = Field(default=0, ge=0, le=10)


class AppAccountView(BaseModel):
    """One of the customer's accounts."""

    id: str
    product: str
    status: str
    card_status: str
    balance: int


class AppTransactionView(BaseModel):
    """One of the customer's own transactions."""

    id: str
    account_id: str
    occurred_at: datetime
    direction: str
    amount: int
    merchant_name: str
    merchant_category: str
    country: str
    channel: str


class AppMeView(BaseModel):
    """What the customer app shows: the customer's accounts and recent activity."""

    customer_id: str
    display_name: str
    home_country: str
    accounts: list[AppAccountView]
    recent: list[AppTransactionView]


class PaymentView(BaseModel):
    """The bank's answer to a payment."""

    transaction_id: str
    balance_after: int
    account_status: str


class ScenarioView(BaseModel):
    """A sample alert from the synthetic scenarios, ready to open as a case."""

    id: str
    title: str
    description: str
    account_id: str
    customer_id: str
    transaction_id: str
    trigger: str


class FindingView(BaseModel):
    """One finding: a code from the closed vocabulary and our own summary of it."""

    id: str
    code: str
    signal: str
    summary: str


class CandidateView(BaseModel):
    """One ranked action. The score orders candidates; it is not a probability."""

    action: str
    score: float


class PolicyRefView(BaseModel):
    """A cited policy clause."""

    doc_id: str
    version: str
    section: str | None


class DecisionView(BaseModel):
    """The recommendation. It is advice: nothing runs without an approval."""

    recommended_action: str
    risk_level: int
    approval_required: bool
    overridden_by: str | None
    uncertainty_flags: list[str]
    evidence_strength: float
    provider: str
    candidates: list[CandidateView]
    policy_refs: list[PolicyRefView]


class VoteView(BaseModel):
    """A recorded vote."""

    approver_id: str
    role: str
    verdict: str
    decided_at: datetime


class ApprovalView(BaseModel):
    """The approval request and who has voted so far."""

    id: str
    action: str
    target_account_id: str
    required_roles: list[str]
    expires_at: datetime
    status: str | None
    votes: list[VoteView]


class CaseSummary(BaseModel):
    """One line per case, for lists."""

    id: str
    status: str
    recommended_action: str | None
    awaiting_approval: bool


class CaseView(BaseModel):
    """Everything the screen needs about one case."""

    id: str
    status: str
    trail: list[str]
    failure: str | None
    alert_id: str
    transaction_id: str
    account_id: str
    trigger: str
    findings: list[FindingView]
    uncertainty_flags: list[str]
    decision: DecisionView | None
    approval: ApprovalView | None


class AuditEventView(BaseModel):
    """One audit event (detail holds statuses, ids and codes only)."""

    id: str
    timestamp: datetime
    event_type: str
    actor: str
    tool_name: str | None
    detail: str
    event_hash: str


class PassageView(BaseModel):
    """One cited passage in a chat answer."""

    title: str
    document_id: str
    version: str
    section: str
    text: str


class ChatResponse(BaseModel):
    """The cited passages the caller is cleared to see."""

    passages: list[PassageView]


def summary_of(run: CaseRun) -> CaseSummary:
    """Reduce a run to a list row."""
    return CaseSummary(
        id=run.case.id,
        status=run.case.status.value,
        recommended_action=run.decision.recommended_action.value if run.decision else None,
        awaiting_approval=run.awaiting_approval,
    )


def view_of(run: CaseRun) -> CaseView:
    """Turn a run into the response for a case screen."""
    case, inv = run.case, run.investigation
    findings = [
        FindingView(
            id=e.id,
            code=code.value,
            signal=signal.value if (signal := signal_of(e)) else "",
            summary=e.summary,
        )
        for e in (inv.findings if inv else ())
        if (code := code_of(e)) is not None
    ]
    decision = None
    if run.decision is not None:
        d = run.decision
        decision = DecisionView(
            recommended_action=d.recommended_action.value,
            risk_level=int(d.risk_level),
            approval_required=d.approval_required,
            overridden_by=d.overridden_by,
            uncertainty_flags=[f.value for f in d.uncertainty_flags],
            evidence_strength=d.evidence_strength,
            provider=d.provider,
            candidates=[
                CandidateView(action=c.action.value, score=c.score) for c in d.ranked_candidates
            ],
            policy_refs=[
                PolicyRefView(doc_id=r.doc_id, version=r.version, section=r.section)
                for r in d.policy_refs
            ],
        )
    approval = None
    if run.approval_request is not None:
        r = run.approval_request
        approval = ApprovalView(
            id=r.id,
            action=r.action.value,
            target_account_id=r.target_account_id,
            required_roles=[role.value for role in r.required_roles],
            expires_at=r.expires_at,
            status=run.approval.value if run.approval else None,
            votes=[
                VoteView(
                    approver_id=v.approver_id,
                    role=v.role.value,
                    verdict=v.verdict.value,
                    decided_at=v.decided_at,
                )
                for v in run.votes
            ],
        )
    return CaseView(
        id=case.id,
        status=case.status.value,
        trail=[s.value for s in run.trail],
        failure=run.failure,
        alert_id=case.alert.id,
        transaction_id=case.alert.transaction_id,
        account_id=case.alert.account_id,
        trigger=case.alert.trigger,
        findings=findings,
        uncertainty_flags=[f.value for f in inv.verification.uncertainty_flags] if inv else [],
        decision=decision,
        approval=approval,
    )

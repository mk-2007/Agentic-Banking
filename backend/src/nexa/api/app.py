"""The HTTP layer: authenticate, check the role, delegate to the service, shape the answer.

No business rules live here. Approval is judged by the pure approval rule inside the graph,
execution is guarded by the tool, and every route that changes anything is for employees only. Who
a voter is and which role they vote as come from their token, never from the request body.

    POST /cases                 open and run a case from an alert           (employee)
    GET  /cases, /cases/{id}    list and view cases                         (employee)
    GET  /cases/{id}/audit      the case's audit chain                      (employee)
    GET  /approvals/pending     cases waiting for votes                     (employee)
    POST /cases/{id}/votes      cast a verdict and continue the case        (employee)
    POST /chat                  answer from the knowledge base              (customer or employee)
    GET  /scenarios             sample alerts to open cases from            (employee)
    GET  /app/me, POST /app/payments   the customer's accounts and payments         (customer)
    GET  /monitor/log           payments the monitor reviewed and what it did   (employee)
    GET  /admin/...             lab cases, run, scorecard, reports, accounts (auditor only)
    GET  /health                liveness, no authentication
    GET  /                      the dashboard page (static; every call it makes needs a token)
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse

from nexa.bank_sim import (
    AccountFrozenError,
    InsufficientFundsError,
    RecordNotFoundError,
    load_scenarios,
)
from nexa.domain.actors import Role

from .lab import (
    AccountProfile,
    AccountRow,
    BaselineRow,
    HostileRow,
    LabCaseRow,
    LabReport,
    LabRunRequest,
    LabRunView,
    LabService,
    LiveView,
    ScorecardView,
    UnknownLabCaseError,
)
from .live import LiveService, NotYourAccountError
from .monitor import Monitor
from .principals import Principal
from .schemas import (
    AppMeView,
    AuditEventView,
    CaseSummary,
    CaseView,
    ChatRequest,
    ChatResponse,
    MonitorEntryView,
    OpenCaseRequest,
    PassageView,
    PaymentRequest,
    PaymentView,
    ScenarioView,
    VoteRequest,
    summary_of,
    view_of,
)
from .service import CaseNotFoundError, CaseService, InvalidAlertError, NotWaitingError


def create_app(
    service: CaseService,
    principals: Mapping[str, Principal],
    lab: LabService | None = None,
    monitor: Monitor | None = None,
) -> FastAPI:
    """Build the API around ``service``. ``principals`` maps bearer tokens to callers.

    ``lab`` is the auditor's evaluation lab; it is built on first use if not given. With a
    ``monitor`` every payment made in the customer app is reviewed in the background.
    """
    app = FastAPI(title="NexaBank Agentic Platform", version="0.1.0")
    lab_box: list[LabService] = [lab] if lab else []

    def caller(authorization: Annotated[str | None, Header()] = None) -> Principal:
        scheme, _, token = (authorization or "").partition(" ")
        principal = principals.get(token) if scheme.lower() == "bearer" else None
        if principal is None:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "missing or unknown token",
                {"WWW-Authenticate": "Bearer"},
            )
        return principal

    def employee(who: Annotated[Principal, Depends(caller)]) -> Principal:
        if not who.is_employee:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "employees only")
        return who

    def customer(who: Annotated[Principal, Depends(caller)]) -> Principal:
        if who.role is not Role.CUSTOMER or who.customer_id is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "customers linked to a bank customer only"
            )
        return who

    live = LiveService(service.bank, service.now)

    def auditor(who: Annotated[Principal, Depends(caller)]) -> Principal:
        if not who.is_auditor:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "auditors only")
        return who

    def the_lab() -> LabService:
        if not lab_box:
            lab_box.append(LabService())
        return lab_box[0]

    Who = Annotated[Principal, Depends(caller)]
    Employee = Annotated[Principal, Depends(employee)]
    Auditor = Annotated[Principal, Depends(auditor)]
    Customer = Annotated[Principal, Depends(customer)]
    Lab = Annotated[LabService, Depends(the_lab)]

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness check."""
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        """Serve the single-page dashboard; it holds no data and its API calls carry a token."""
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.get("/scenarios")
    def scenarios(who: Employee) -> list[ScenarioView]:
        """Sample alerts (synthetic) so a demo can open a case without typing ids."""
        return [
            ScenarioView(
                id=s.id,
                title=s.title,
                description=s.description,
                **s.alert.model_dump(
                    include={"account_id", "customer_id", "transaction_id", "trigger"}
                ),
            )
            for s in load_scenarios()
        ]

    @app.post("/cases", status_code=status.HTTP_201_CREATED)
    def open_case(body: OpenCaseRequest, who: Employee) -> CaseView:
        """Open a case from an alert and run it through the graph."""
        try:
            return view_of(service.open_case(**body.model_dump()))
        except RecordNotFoundError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from None
        except InvalidAlertError as error:
            raise HTTPException(422, str(error)) from None

    @app.get("/cases")
    def list_cases(who: Employee) -> list[CaseSummary]:
        """Every case, oldest first."""
        return [summary_of(run) for run in service.all_runs()]

    @app.get("/cases/{case_id}")
    def get_case(case_id: str, who: Employee) -> CaseView:
        """One case with its findings, decision and approval."""
        try:
            return view_of(service.get(case_id))
        except CaseNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such case") from None

    @app.get("/cases/{case_id}/audit")
    def case_audit(case_id: str, who: Employee) -> list[AuditEventView]:
        """Return the audit events recorded for a case."""
        try:
            events = service.audit(case_id)
        except CaseNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such case") from None
        return [
            AuditEventView(
                id=e.id,
                timestamp=e.timestamp,
                event_type=e.event_type.value,
                actor=f"{e.actor.kind.value}:{e.actor.id}",
                tool_name=e.tool_name,
                detail=e.detail,
                event_hash=e.event_hash,
            )
            for e in events
        ]

    @app.get("/approvals/pending")
    def pending(who: Employee) -> list[CaseView]:
        """Cases waiting for votes."""
        return [view_of(run) for run in service.pending()]

    @app.post("/cases/{case_id}/votes")
    def vote(case_id: str, body: VoteRequest, who: Employee) -> CaseView:
        """Cast the caller's verdict. The approver and role are the authenticated caller's."""
        try:
            return view_of(service.vote(case_id, who, body.verdict, body.comment))
        except CaseNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such case") from None
        except NotWaitingError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None

    @app.post("/chat")
    def chat(body: ChatRequest, who: Who) -> ChatResponse:
        """Answer from the knowledge base; what is returned depends on the caller's channel."""
        return ChatResponse(
            passages=[PassageView(**vars(p)) for p in service.chat(body.question, who)]
        )

    # --- the customer app ----------------------------------------------------------------------
    @app.get("/app/me")
    def app_me(who: Customer) -> AppMeView:
        """Return the signed-in customer's accounts and recent activity."""
        assert who.customer_id is not None
        return live.me(who.customer_id)

    @app.post("/app/payments", status_code=status.HTTP_201_CREATED)
    def app_pay(body: PaymentRequest, who: Customer) -> PaymentView:
        """Make a payment from one of the customer's own accounts."""
        assert who.customer_id is not None
        try:
            record, view = live.pay(who.customer_id, body)
        except RecordNotFoundError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from None
        except NotYourAccountError:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not your account") from None
        except (AccountFrozenError, InsufficientFundsError) as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None
        if monitor is not None:
            monitor.watch(record)  # reviewed in the background; the payment is already posted
        return view

    @app.get("/monitor/log")
    def monitor_log(who: Employee) -> list[MonitorEntryView]:
        """Return every payment the monitor reviewed, newest first (empty if it is off)."""
        entries = monitor.entries() if monitor is not None else []
        return [
            MonitorEntryView(
                transaction_id=e.transaction_id,
                account_id=e.account_id,
                amount=e.amount,
                observed_at=e.observed_at,
                phase=e.phase.value,
                decision=e.decision.value if e.decision else None,
                path=e.path.value if e.path else None,
                reasons=list(e.reasons),
                case_id=e.case_id,
                case_status=e.case_status,
            )
            for e in entries
        ]

    # --- the auditor's lab -------------------------------------------------------------------
    @app.get("/admin/lab/cases")
    def lab_cases(who: Auditor, lab: Lab) -> list[LabCaseRow]:
        """Every labelled case, with its latest score if it has been run."""
        return lab.cases()

    @app.post("/admin/lab/run")
    def lab_run(body: LabRunRequest, who: Auditor, lab: Lab) -> LabRunView:
        """Run the chosen cases (all by default) on a private platform copy and score them."""
        try:
            return lab.run(body.ids, body.archetype)
        except UnknownLabCaseError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no such lab case: {error}") from None

    @app.get("/admin/lab/scorecard")
    def lab_scorecard(who: Auditor, lab: Lab) -> ScorecardView:
        """Headline numbers over the cases run so far."""
        return lab.scorecard()

    @app.get("/admin/lab/cases/{case_id}")
    def lab_report(case_id: str, who: Auditor, lab: Lab) -> LabReport:
        """Return the full report for one case: label, run, audit chain and account."""
        try:
            return lab.report(case_id)
        except UnknownLabCaseError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such lab case") from None

    @app.get("/admin/lab/baselines")
    def lab_baselines(who: Auditor, lab: Lab) -> list[BaselineRow]:
        """Return the agents and simple rules scored on the same cases with the same checks."""
        return lab.baselines()

    @app.get("/admin/lab/hostile")
    def lab_hostile(who: Auditor, lab: Lab) -> list[HostileRow]:
        """Misbehaving stand-in models behind the real gates."""
        return lab.hostile()

    @app.get("/admin/lab/live")
    def lab_live(who: Auditor, lab: Lab) -> LiveView:
        """Return the latest saved comparison of a real model against the rules, if one was run."""
        return lab.live()

    @app.get("/admin/accounts")
    def admin_accounts(who: Auditor, lab: Lab) -> list[AccountRow]:
        """Every synthetic account, with its lab case if one exists."""
        return lab.accounts()

    @app.get("/admin/accounts/{account_id}")
    def admin_account(account_id: str, who: Auditor, lab: Lab) -> AccountProfile:
        """One account's profile (no merchant names or memos)."""
        try:
            return lab.account(account_id)
        except UnknownLabCaseError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such account") from None

    return app

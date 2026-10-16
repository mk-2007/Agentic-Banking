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
    GET  /health                liveness, no authentication
"""

from collections.abc import Mapping
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status

from nexa.bank_sim import RecordNotFoundError

from .principals import Principal
from .schemas import (
    AuditEventView,
    CaseSummary,
    CaseView,
    ChatRequest,
    ChatResponse,
    OpenCaseRequest,
    PassageView,
    VoteRequest,
    summary_of,
    view_of,
)
from .service import CaseNotFoundError, CaseService, InvalidAlertError, NotWaitingError


def create_app(service: CaseService, principals: Mapping[str, Principal]) -> FastAPI:
    """Build the API around ``service``. ``principals`` maps bearer tokens to callers."""
    app = FastAPI(title="NexaBank Agentic Platform", version="0.1.0")

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

    Who = Annotated[Principal, Depends(caller)]
    Employee = Annotated[Principal, Depends(employee)]

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness check."""
        return {"status": "ok"}

    @app.post("/cases", status_code=status.HTTP_201_CREATED)
    def open_case(body: OpenCaseRequest, who: Employee) -> CaseView:
        """Open a case from an alert and run it through the graph."""
        try:
            return view_of(service.open_case(**body.model_dump()))
        except RecordNotFoundError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from None
        except InvalidAlertError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None

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

    return app

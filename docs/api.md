# HTTP API (Phase 8a)

A thin FastAPI layer over the platform. Code: `backend/src/nexa/api/`. Run it:

```
python scripts/run_api.py --demo            # random demo tokens, printed once
python scripts/run_api.py --demo --llm      # decide with the LLM provider (rules as fallback)
```

Interactive docs are served at `/docs`. Everything is held in memory: restarting forgets cases, approvals and the
audit log, and demo tokens change on every start.

## Routes

| Route | Who | What |
|---|---|---|
| `GET /health` | anyone | liveness |
| `POST /cases` | employee | open a case from an alert (`account_id`, `customer_id`, `transaction_id`, `trigger`) and run it |
| `GET /cases`, `GET /cases/{id}` | employee | list cases; one case with findings, decision and approval |
| `GET /cases/{id}/audit` | employee | the case's audit events |
| `GET /approvals/pending` | employee | cases waiting for votes |
| `POST /cases/{id}/votes` | employee | cast `approve`, `reject`, `escalate` or `modify` and continue the case |
| `POST /chat` | customer or employee | cited passages from the knowledge base |

Employees are the fraud analyst, risk officer and compliance officer roles. A customer can only chat.

## Rules this layer keeps

- **Who voted comes from the token, never from the body.** A vote carries only a verdict and an optional comment;
  the approver id and role are the authenticated caller's. Extra fields are rejected (422). This closes the gap
  noted in `docs/orchestration.md` ("the graph trusts that votes come from authenticated approvers").
- **The channel is trusted input derived from the role.** Staff get the employee channel, customers the customer
  channel. It is never read from a request, so no phrasing of a question widens a customer's access.
- **Chat goes through the tool layer.** A customer is served as the chatbot (the customer-service agent role:
  public knowledge only); an employee asks as themselves with their own role's clearance. Both are audited. Agents
  must name a case, so the chatbot names a conversation id (`chat_<user>`).
- **The alert must match the bank.** The transaction must belong to the account and the account to the customer
  (422), and the transaction must exist (404). The case's scope is then limited to that customer and account.
- **Responses leave out the dossier**, so merchant names, memos and customer details stay inside the platform.
  Findings appear as codes with our own summaries. A test checks that the injection scenario's memo text appears
  in neither the case nor the audit responses.
- **Approval and execution are not here.** The route only forwards the verdict; the pure approval rule judges it
  and the guarded tool executes. The same tests prove one approver is not enough, one role voting twice is not two
  approvers, a rejection changes nothing, and a case that is no longer waiting answers 409.

## Sign-in

Bearer tokens map to a user id and a role. Provide them as `NEXA_API_TOKENS="token:user_id:role,..."` (roles:
`fraud_analyst`, `risk_officer`, `compliance_officer`, `customer`), or use `--demo` for random ones. Tokens are
never in the repository.

## Honest limits

- **Authentication is a static bearer token held in memory.** There is no identity provider, expiry, rotation or
  rate limiting. A real deployment needs those in front.
- **Customers are not linked to bank customers.** A customer principal can chat, but the API does not check that it
  is asking about its own accounts, because chat reads only policy and product knowledge.
- **Every employee sees every case.** There is no per-team or per-branch visibility.
- **One process, one lock.** Requests that open or vote on cases are serialised, and state is lost on restart. The
  LangGraph checkpoint store is in memory (the saved-state format is tested, a database store is not).
- **Chat returns cited passages, not a written answer.** There is no model rewriting them; that keeps every word
  traceable to a document and version.
- **Opening a case runs the whole investigation synchronously.** With the LLM provider that can take seconds.
- No CORS settings yet; the frontend (8b) will need them.

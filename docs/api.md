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
| `GET /app/me` | customer (linked to a bank customer) | the customer's own accounts and recent transactions |
| `POST /app/payments` | customer (linked) | pay from one of the customer's own accounts; the bank posts it |
| `GET /admin/lab/cases` | auditor | the 98 labelled lab cases with their latest score |
| `POST /admin/lab/run` | auditor | run all cases, some `ids`, or one `archetype` on a private platform copy and score them |
| `GET /admin/lab/scorecard` | auditor | pass, safe, useful and human-routed rates over the cases run so far |
| `GET /admin/lab/cases/{id}` | auditor | one case's report: label, run, audit chain and account profile |
| `GET /admin/lab/baselines` | auditor | the agents and five simple rules scored on the same cases with the same checks |
| `GET /admin/lab/hostile` | auditor | misbehaving stand-in models behind the real gates: unsafe if accepted versus unsafe after the gates |
| `GET /admin/lab/live` | auditor | the latest saved run of a real model against the rules (`python scripts/run_lab_live.py`), or `available: false` |
| `GET /admin/accounts`, `GET /admin/accounts/{id}` | auditor | every synthetic account; one profile (no merchant names or memos) |

Employees are the fraud analyst, risk officer and compliance officer roles. A customer can only chat. The auditor is not an employee: it cannot open live cases or vote, and it alone may use `/admin`. Lab runs use their own platform copy and never appear among live cases.

## The customer app

`POST /app/payments` is how live data enters the bank. The body is what a customer would type (amount, payee, category, channel, country, city, optional payee account) plus two controls that stand in for the bank's own sensors: `device` (registered or new) and `failed_logins`. Everything else is decided by the bank, never asked: whether the device is trusted (the customer's registered device list), whether the payee is a new beneficiary (not paid before the last 24 hours), the timestamp and the id. A customer can only pay from their own accounts (403 otherwise); a frozen account or an overdraft is refused (409); unknown fields such as a memo or `is_new_beneficiary` are rejected (422). A freeze decided by a case is therefore visible straight away: the same customer's next payment is refused.

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

Bearer tokens map to a user id and a role; a customer token may also name the bank customer it belongs to (`token:user_id:customer:cust_010`). Without that link the customer can chat but not use the app.

Bearer tokens map to a user id and a role. Provide them as `NEXA_API_TOKENS="token:user_id:role,..."` (roles:
`fraud_analyst`, `risk_officer`, `compliance_officer`, `auditor`, `customer`), or use `--demo` for random ones. Tokens are
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
- **The dashboard is one static page at `/`** (`api/static/index.html`, no build step). It is served by the API itself, so
  there is no cross-origin traffic and no CORS setup. You paste a token; it is kept in `sessionStorage` for the tab
  only. All API text is inserted with `textContent`, never as HTML. `GET /scenarios` (employee) lists the synthetic
  sample alerts so a demo can open a case with one click.

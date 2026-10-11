# Security model (Phase 3)

The goal: **an AI agent can investigate and recommend, but it cannot change the bank, read what it
should not, or act without leaving a tamper-evident trace.** Every guarantee below is enforced in
plain code and covered by tests; none relies on a prompt.

## The path of every tool call

```
agent / human / service
        |  ToolCall(actor, tool, arguments, case_id, approval_id)
        v
  ToolRegistry.invoke
   1. unknown tool?                     -> denied   (deny by default)
   2. actor's role in the config matrix? -> else denied
   3. agent without a case?             -> denied
   4. audit TOOL_CALLED  (before running, with input hash)
   5. validate arguments (extra fields rejected)
   6. tool.run: case-scope check, approval gate (execution only)
   7. audit TOOL_COMPLETED / TOOL_DENIED (with output hash, never raw data)
        v
     ToolResult   (always returned; errors never crash the platform)
```

## Guarantees and where they are tested

| Guarantee | Enforced by | Tests |
|---|---|---|
| Nothing is permitted by omission: unknown tools, unknown roles, roleless actors are denied | `security.permissions`, registry | `test_authorization.py`, full role x tool matrix in `test_tool_registry.py` |
| Tool access is configuration; a tool whose roles differ from the matrix cannot be registered | `config.tool_permissions`, `ToolRegistry.register` | registration tests |
| An agent sees only its own case's customer and accounts | `security.scope`, `ToolContext.require_scope` | scope tests (5 tools, wrong case, unknown case) |
| Contact details never leave the bank layer; names are initials; addresses are compared, not returned | read tools | privacy tests |
| Third-party free text is labelled untrusted and kept out of history rows | read tools | injection and history tests |
| Only the execution service can change the bank, and only via `execute_authorized_action` | role matrix, approval gate | `test_execution_gate.py` |
| An approval authorizes **one action, on one account, for one case, once**, until it expires | `security.approval_gate` + `try_consume` | mismatch, replay, expiry, rejection, two-role tests |
| Scenario E (a data agent tries to freeze an account) is refused and recorded | role matrix + audit | `test_scenario_e_...` (driven by the scenario data) |
| Every call and denial leaves audit events; the log stores hashes, not raw data | `ToolRegistry`, `audit` | audit tests |
| Editing, deleting or reordering history is detected, including between runs | hash chain, `JsonlAuditLog` | tamper tests |
| Tool bugs return `internal_error` without leaking details | registry | crashing-tool test |

## Roles that matter

Data agent: read profile, account, KYC, transactions. Analysis agent: read transactions. Human
investigators: the same reads, never execution. **Execution service**: the only holder of
`execute_authorized_action`. Agents can never claim the service role (the `Actor` contract
rejects it).

## Honest limits (what Phase 3 does not do)

- **Authentication is outside the tool layer.** The registry trusts the `Actor` it is given; the API
  layer (Phase 8) must establish who a human really is, and orchestration code (never an LLM) builds
  agent actors.
- **Case scope and approvals are interfaces.** Real implementations arrive with approvals and
  orchestration (Phase 6). `ApprovalSource.try_consume` must be atomic there.
- **Human investigators are not scope-limited**, only role-limited and audited.
- **The hash chain detects edits but cannot stop someone who rewrites the whole file.** In
  production the head hash would be anchored externally (for example periodically signed or stored in
  a separate system).
- A consumed approval stays consumed even if the bank action then fails; a new approval is required.
- Reading a transaction outside scope reveals "out of scope" rather than "not found" only after the
  record is looked up, a minor existence leak acceptable for the prototype.

# ADR 0005: Deny by default; approvals are single-use and bound to one target

- Status: accepted
- Date: 2026-10-11

## Context
Agents are untrusted callers. The tool layer is the only door to the bank, so its rules must hold
even if an agent is confused, manipulated by injected text, or buggy.

## Decision
1. Tool access is a configuration matrix (`config/tool_permissions.py`). Unknown tools, unknown roles and
   roleless actors are denied. Tools must match the matrix to be registered.
2. Agents are scoped to their case's customer and accounts.
3. State changes exist in exactly one tool, callable only by a dedicated execution-service role.
4. An approval authorizes one action on one account in one case, once, until it expires. Execution
   verifies all of that and consumes the approval before acting.
5. Every call is audited before it runs and after it finishes; the log keeps hashes, not payloads.
6. Read tools minimise data: no contact details, masked names, third-party text labelled untrusted.

Domain changes this required: `Role.EXECUTION_SERVICE` (system actors may hold only service roles),
`ApprovalRequest.target_account_id`, `AuditEventType.TOOL_COMPLETED`, `ToolResult.output` as JSON, and
an injectable `Clock`.

## Consequences
- Good: the guarantees are testable without any model, and Scenario E becomes a passing test.
- Good: replacing an agent or a model cannot widen what the platform allows.
- Cost: every new tool needs a matrix entry and tests; approvals need an atomic store in Phase 6.

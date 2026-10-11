# Project log

Newest first. Add an entry whenever a step is finished or a decision is made.

## 2026-10-11 - Phase 3: security, audit and tool layer
- `security`: role check (deny by default), per-case scope for agents, approval gate (one action, one account, one case, once, unexpired).
- `config`: tool permission matrix is the single source of truth; tools that differ cannot register.
- `audit`: append-only log with JSONL persistence; reopening a tampered file raises `AuditTamperedError`.
- `tools`: registry (authorize, audit before/after, error handling), five privacy-minimised read tools, one guarded execution tool.
- Scenario E passes: a data agent's freeze attempt is refused and recorded. Replay, wrong account/case/action, missing second approver, rejection and expiry are all refused.
- Domain changes: `Role.EXECUTION_SERVICE`, `ApprovalRequest.target_account_id`, `AuditEventType.TOOL_COMPLETED`, `Clock` (ADR 0005).
- 256 tests pass. Next: Phase 4, RAG over the knowledge base and policy documents.

## 2026-10-10 - Phase 2: simulated bank, data and policies
- Added `bank_sim`: record models, `BankGateway` Protocols (customer, account, transaction, KYC, actions) and a deterministic in-memory bank (ADR 0004).
- Added `config`: fraud thresholds and the approval matrix (Level 4 = fraud analyst + risk officer; expiries 60/120/240 minutes).
- Added a deterministic data generator and committed dataset (23 customers, 865 transactions); a test regenerates it to prove it matches.
- Defined 7 scenarios as data: PRD A-E plus F (account takeover, Level 4 approval) and X (prompt injection).
- Wrote 3 synthetic policy documents with KB section 19.2 metadata; a test keeps their numbers identical to config.
- 107 tests pass. Next: Phase 3, security + audit + tool layer (before any LLM).

## 2026-10-09 - Phase 1: domain contracts
- Added immutable, strict contracts: actions/risk, actors, evidence, case state machine, decision, approval, tool, audit.
- Safety rules are validators (ADR 0003): unsafe decisions cannot be constructed; Level 4 needs two approver roles; audit events form a hash chain.
- Renamed Level 3/4 actions to `block_card` / `freeze_account` (the action itself; a decision recommends it, a human authorizes it).
- 68 tests pass (unit + architecture). GitHub project scaffolding (templates, labels, seeded issues) lands in a separate PR.
- Next: Phase 2, simulated bank, synthetic data and the fraud/approval policy document.

## 2026-10-09 - Phase 0: scaffold
- Chose the investigation workflow: suspicious-transaction investigation ending in a Level 4 account-freeze recommendation.
- Decided to build without JEV (no access); decision layer is a swappable provider (ADR 0002).
- Created repo layout, tooling (ruff, mypy strict, pytest), CI, architecture tests, context graph.
- Next: Phase 1, domain contracts.

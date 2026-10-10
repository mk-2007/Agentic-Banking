# Project log

Newest first. Add an entry whenever a step is finished or a decision is made.

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
